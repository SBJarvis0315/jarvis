<?php
/**
 * Plugin Name: Notion Publish Bridge
 * Description: 노션 콘텐츠 플래너 자동 발행을 위한 Rank Math 메타·스키마 기입 엔드포인트.
 * Version:     1.0.1
 * Author:      리드젠랩
 *
 * 설치: 이 파일을 wp-content/mu-plugins/ 에 업로드하면 끝입니다.
 *       (mu-plugins 폴더가 없으면 새로 만드세요. 별도 활성화 과정이 없습니다.)
 *
 * 왜 필요한가:
 *   워드프레스 REST API는 등록되지 않은 커스텀 메타를 "에러 없이 조용히" 버립니다.
 *   Rank Math는 모든 SEO 값을 커스텀 메타에 저장하므로, 이 파일이 없으면
 *   글은 정상 발행되지만 Rank Math 항목만 전부 비어 있게 됩니다.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Notion_Publish_Bridge {

	const NS = 'notion-bridge/v1';

	/** 노션 페이지 ID를 담아두는 메타 키. 중복 발행 방지용. */
	const NOTION_ID_META = '_notion_page_id';

	/** schema_mode=jsonld 일 때 원본 JSON-LD를 담아두는 메타 키. */
	const JSONLD_META = '_notion_jsonld';

	public static function init() {
		add_action( 'init', array( __CLASS__, 'register_meta' ) );
		add_action( 'rest_api_init', array( __CLASS__, 'register_routes' ) );
		add_filter( 'rank_math/json_ld', array( __CLASS__, 'inject_jsonld' ), 99, 2 );
	}

	/**
	 * 메타 키를 REST에 노출. 단순 스칼라 값은 이걸로도 쓸 수 있지만,
	 * 스키마처럼 중첩 배열인 값은 아래 커스텀 엔드포인트를 통해야 안전합니다.
	 */
	public static function register_meta() {
		$scalar_keys = array(
			'rank_math_title',
			'rank_math_description',
			'rank_math_focus_keyword',
			'rank_math_canonical_url',
			self::NOTION_ID_META,
		);

		foreach ( $scalar_keys as $key ) {
			register_post_meta(
				'post',
				$key,
				array(
					'type'          => 'string',
					'single'        => true,
					'show_in_rest'  => true,
					'auth_callback' => function () {
						return current_user_can( 'edit_posts' );
					},
				)
			);
		}
	}

	public static function register_routes() {
		// 노션 페이지 ID로 이미 발행된 글이 있는지 조회 (멱등성).
		register_rest_route(
			self::NS,
			'/lookup',
			array(
				'methods'             => 'GET',
				'callback'            => array( __CLASS__, 'handle_lookup' ),
				'permission_callback' => array( __CLASS__, 'can_edit_posts' ),
				'args'                => array(
					'notion_page_id' => array(
						'required'          => true,
						'type'              => 'string',
						'sanitize_callback' => 'sanitize_text_field',
					),
				),
			)
		);

		// Rank Math 메타 + 스키마 일괄 기입.
		register_rest_route(
			self::NS,
			'/seo/(?P<post_id>\d+)',
			array(
				'methods'             => 'POST',
				'callback'            => array( __CLASS__, 'handle_seo' ),
				'permission_callback' => array( __CLASS__, 'can_edit_target_post' ),
			)
		);

		// 설치 확인용.
		register_rest_route(
			self::NS,
			'/ping',
			array(
				'methods'             => 'GET',
				'callback'            => array( __CLASS__, 'handle_ping' ),
				'permission_callback' => array( __CLASS__, 'can_edit_posts' ),
			)
		);
	}

	public static function can_edit_posts() {
		return current_user_can( 'edit_posts' );
	}

	public static function can_edit_target_post( WP_REST_Request $request ) {
		$post_id = (int) $request['post_id'];
		return $post_id > 0 && current_user_can( 'edit_post', $post_id );
	}

	public static function handle_ping() {
		return array(
			'ok'             => true,
			'version'        => '1.0.1',
			'rank_math'      => defined( 'RANK_MATH_VERSION' ) ? RANK_MATH_VERSION : null,
			'rank_math_active' => class_exists( 'RankMath' ),
		);
	}

	public static function handle_lookup( WP_REST_Request $request ) {
		$notion_page_id = self::normalize_uuid( $request->get_param( 'notion_page_id' ) );

		$posts = get_posts(
			array(
				'post_type'        => 'post',
				'post_status'      => 'any',
				'numberposts'      => 1,
				'fields'           => 'ids',
				'suppress_filters' => false,
				'meta_query'       => array(
					array(
						'key'   => self::NOTION_ID_META,
						'value' => $notion_page_id,
					),
				),
			)
		);

		if ( empty( $posts ) ) {
			return array( 'found' => false );
		}

		$post_id = (int) $posts[0];

		return array(
			'found'   => true,
			'post_id' => $post_id,
			'status'  => get_post_status( $post_id ),
			'link'    => get_permalink( $post_id ),
		);
	}

	/**
	 * 본체. Rank Math 메타를 쓰고, 기존 스키마를 정리한 뒤 새 스키마를 붙입니다.
	 *
	 * 기대 페이로드:
	 * {
	 *   "notion_page_id": "...",
	 *   "rank_math_title": "...",
	 *   "rank_math_description": "...",
	 *   "rank_math_focus_keyword": "메인, 서브1, 서브2",
	 *   "rank_math_canonical_url": "https://...",
	 *   "seo_score": 0,
	 *   "schema_mode": "rankmath" | "jsonld",
	 *   "schemas": [ { "@type": "BlogPosting", ... }, { "@type": "FAQPage", ... } ]
	 * }
	 */
	public static function handle_seo( WP_REST_Request $request ) {
		$post_id = (int) $request['post_id'];
		$post    = get_post( $post_id );

		if ( ! $post ) {
			return new WP_Error( 'notion_bridge_no_post', '해당 글을 찾을 수 없습니다.', array( 'status' => 404 ) );
		}

		$body = $request->get_json_params();
		if ( ! is_array( $body ) ) {
			return new WP_Error( 'notion_bridge_bad_body', 'JSON 본문이 필요합니다.', array( 'status' => 400 ) );
		}

		$written = array();

		$text_fields = array(
			'rank_math_title'         => 'sanitize_text_field',
			'rank_math_description'   => 'sanitize_textarea_field',
			'rank_math_focus_keyword' => 'sanitize_text_field',
			'rank_math_canonical_url' => 'esc_url_raw',
		);

		foreach ( $text_fields as $key => $sanitizer ) {
			if ( ! isset( $body[ $key ] ) || '' === $body[ $key ] ) {
				continue;
			}
			update_post_meta( $post_id, $key, call_user_func( $sanitizer, $body[ $key ] ) );
			$written[] = $key;
		}

		if ( isset( $body['notion_page_id'] ) && '' !== $body['notion_page_id'] ) {
			update_post_meta( $post_id, self::NOTION_ID_META, self::normalize_uuid( $body['notion_page_id'] ) );
			$written[] = self::NOTION_ID_META;
		}

		// Rank Math의 점수는 에디터 JS가 계산합니다. 값을 넘겨주면 그대로 반영하고,
		// 없으면 건드리지 않습니다(0으로 덮어써서 목록이 빨갛게 보이는 걸 피하기 위함).
		if ( isset( $body['seo_score'] ) && is_numeric( $body['seo_score'] ) ) {
			update_post_meta( $post_id, 'rank_math_seo_score', (int) $body['seo_score'] );
			$written[] = 'rank_math_seo_score';
		}

		// 스키마는 'schemas' 키가 실제로 실려 왔을 때만 손댑니다.
		// 이 키가 없다고 기존 스키마를 지워버리면, 메타 한 줄만 고치려는 호출이
		// 애써 만든 스키마를 통째로 날리게 됩니다.
		$schema_mode   = isset( $body['schema_mode'] ) ? $body['schema_mode'] : 'rankmath';
		$schema_result = null;

		if ( array_key_exists( 'schemas', $body ) ) {
			$schemas       = is_array( $body['schemas'] ) ? $body['schemas'] : array();
			$schema_result = self::apply_schemas( $post_id, $schemas, $schema_mode );
		}

		return array(
			'ok'          => true,
			'post_id'     => $post_id,
			'written'     => $written,
			'schema_mode' => $schema_mode,
			'schemas'     => $schema_result,          // null = 이번 호출에서 손대지 않음
			'schemas_kept' => null === $schema_result,
			'link'        => get_permalink( $post_id ),
		);
	}

	/**
	 * 스키마 적용.
	 *
	 * rankmath 모드: rank_math_schema_{Type} 메타에 저장합니다. Rank Math 스키마 탭에
	 *                그대로 보이므로 팀원이 눈으로 검수하고 수정할 수 있습니다.
	 * jsonld 모드:   원본 JSON-LD를 따로 저장하고 rank_math/json_ld 필터로 출력합니다.
	 *                UI에는 안 보이지만 출력은 확실합니다. rankmath 모드가 어긋날 때의 대비책.
	 */
	private static function apply_schemas( $post_id, array $schemas, $mode ) {
		// 어느 모드든 먼저 기존 것을 걷어냅니다.
		// 워드프레스가 새 글에 기본으로 붙이는 Article 스키마를 지우라는 내부 가이드와 같은 동작입니다.
		self::purge_rank_math_schemas( $post_id );
		delete_post_meta( $post_id, self::JSONLD_META );

		if ( empty( $schemas ) ) {
			return array();
		}

		if ( 'jsonld' === $mode ) {
			update_post_meta( $post_id, self::JSONLD_META, wp_json_encode( $schemas ) );
			return array_map(
				function ( $s ) {
					return isset( $s['@type'] ) ? $s['@type'] : 'Unknown';
				},
				$schemas
			);
		}

		$applied = array();
		$primary_assigned = false;

		foreach ( $schemas as $schema ) {
			if ( ! is_array( $schema ) || empty( $schema['@type'] ) ) {
				continue;
			}

			$type = preg_replace( '/[^A-Za-z0-9]/', '', (string) $schema['@type'] );
			if ( '' === $type ) {
				continue;
			}

			$schema = self::sanitize_deep( $schema );

			// Rank Math는 각 스키마에 metadata 블록을 요구합니다.
			$schema['metadata'] = array(
				'title'     => $type,
				'type'      => 'template',
				'shortcode' => 's-' . wp_generate_uuid4(),
				'isPrimary' => $primary_assigned ? 0 : 1,
			);
			$primary_assigned = true;

			update_post_meta( $post_id, 'rank_math_schema_' . $type, $schema );
			$applied[] = $type;
		}

		return $applied;
	}

	private static function purge_rank_math_schemas( $post_id ) {
		global $wpdb;

		$keys = $wpdb->get_col(
			$wpdb->prepare(
				"SELECT meta_key FROM {$wpdb->postmeta} WHERE post_id = %d AND meta_key LIKE %s",
				$post_id,
				$wpdb->esc_like( 'rank_math_schema_' ) . '%'
			)
		);

		foreach ( (array) $keys as $key ) {
			delete_post_meta( $post_id, $key );
		}
	}

	/**
	 * 중첩 구조를 유지하면서 스칼라만 정리합니다.
	 * wp_kses 계열을 통째로 돌리면 스키마의 URL·따옴표가 깨지므로 값 종류별로 처리합니다.
	 */
	private static function sanitize_deep( $value ) {
		if ( is_array( $value ) ) {
			$out = array();
			foreach ( $value as $k => $v ) {
				$key         = is_string( $k ) ? sanitize_text_field( $k ) : $k;
				$out[ $key ] = self::sanitize_deep( $v );
			}
			return $out;
		}

		if ( is_bool( $value ) || is_int( $value ) || is_float( $value ) || is_null( $value ) ) {
			return $value;
		}

		$value = (string) $value;

		if ( preg_match( '#^https?://#i', $value ) ) {
			return esc_url_raw( $value );
		}

		// 줄바꿈을 살려야 하는 설명문이 있으므로 textarea 기준으로 정리합니다.
		return sanitize_textarea_field( $value );
	}

	/**
	 * jsonld 모드에서 저장해둔 원본을 Rank Math 출력에 얹습니다.
	 */
	public static function inject_jsonld( $data, $jsonld ) {
		if ( ! is_singular( 'post' ) ) {
			return $data;
		}

		$raw = get_post_meta( get_the_ID(), self::JSONLD_META, true );
		if ( empty( $raw ) ) {
			return $data;
		}

		$schemas = json_decode( $raw, true );
		if ( ! is_array( $schemas ) ) {
			return $data;
		}

		foreach ( $schemas as $i => $schema ) {
			if ( ! is_array( $schema ) || empty( $schema['@type'] ) ) {
				continue;
			}
			$data[ 'notion-' . sanitize_key( $schema['@type'] ) . '-' . $i ] = $schema;
		}

		return $data;
	}

	/** 노션은 하이픈 있는 UUID와 없는 UUID를 섞어 쓰므로 하이픈 형태로 통일합니다. */
	private static function normalize_uuid( $value ) {
		$hex = preg_replace( '/[^a-f0-9]/i', '', (string) $value );

		if ( 32 !== strlen( $hex ) ) {
			return sanitize_text_field( $value );
		}

		return strtolower(
			substr( $hex, 0, 8 ) . '-' .
			substr( $hex, 8, 4 ) . '-' .
			substr( $hex, 12, 4 ) . '-' .
			substr( $hex, 16, 4 ) . '-' .
			substr( $hex, 20, 12 )
		);
	}
}

Notion_Publish_Bridge::init();
