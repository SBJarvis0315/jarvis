<?php
/**
 * Plugin Name: Notion Publish Bridge
 * Description: 노션 콘텐츠 플래너 자동 발행용 엔드포인트. 중복 발행 방지와 Rank Math 메타·스키마 기입에 쓰입니다.
 * Version:     1.2.0
 * Author:      리드젠랩
 *
 * 설치: wp-content/plugins/ 에 이 파일을 올리고 플러그인 목록에서 활성화합니다.
 *       서버가 파일 업로드를 막아 넣지 못하는 고객사도 있습니다. 그런 곳은
 *       Code Snippets 플러그인에 이 코드를 그대로 붙여넣어도 동작이 같습니다
 *       (맨 앞 <?php 한 줄만 빼고, 위치는 '전역에서 실행').
 *
 * 하는 일 (Rank Math 전용이 아닙니다):
 *   1. /lookup      노션 페이지 ID로 이미 발행된 글을 찾습니다. 발행 루틴이 하루 두 번
 *                   돌기 때문에, 이게 없으면 같은 원고가 두 번 올라갑니다.
 *                   Rank Math 와는 아무 상관이 없습니다.
 *   2. /seo/{글번호}  Rank Math 메타와 노션 페이지 ID를 글에 기입합니다. 워드프레스
 *                   REST API 는 등록되지 않은 커스텀 메타를 에러 없이 조용히 버리기
 *                   때문에, 이 경로가 없으면 Rank Math 항목이 전부 비게 되고
 *                   노션 ID 도 안 심겨 1번의 중복 방지까지 무력해집니다.
 *   3. /ping        설치 확인용. 발행 루틴은 시작할 때 이 경로부터 확인하고,
 *                   응답이 없으면 그 고객사 발행을 아예 중단합니다. 이 사이트가
 *                   쓰는 글 종류와 분류 목록도 함께 돌려주므로, 어디에 올려야
 *                   하는지 브라우저로 열어 보기만 해도 알 수 있습니다.
 *
 *   4. /auth-probe  로그인이 왜 안 되는지 알아보는 진단용. 값은 돌려주지 않고,
 *                   어떤 인증 헤더가 PHP까지 닿았는지만 알려줍니다.
 *
 * 인증 헤더를 지우는 서버 대비 (1.2.0):
 *   Authorization 헤더를 PHP까지 넘기지 않는 서버가 있습니다(쉬즈메디 의심).
 *   그런 곳에서는 응용 프로그램 비밀번호가 맞아도 워드프레스가 아무것도 못 받아
 *   'rest_not_logged_in' 만 돌려줍니다. 비밀번호가 틀린 것과 구분이 안 됩니다.
 *   그래서 발행 도구는 같은 자격 증명을 X-Notion-Authorization 헤더에도 함께
 *   보냅니다. 이 플러그인이 그 헤더를 읽어 워드프레스가 보는 자리에 옮겨 놓으면,
 *   인증 자체는 워드프레스 코어가 평소대로 처리합니다. 우리가 비밀번호를 따로
 *   검사하지 않으므로 인증이 느슨해지지 않습니다.
 *
 * 글 종류를 가리지 않습니다 (1.1.0):
 *   개발사가 '용어사전' 같은 별도 글 종류를 만들어 둔 사이트가 있습니다
 *   (비컴성형외과 glossary). 메뉴는 일반 카테고리와 똑같이 생겼지만 속은
 *   다른 글 종류라, 일반 글만 보면 찾지도 기입하지도 못합니다.
 *   이 플러그인은 REST 에 노출된 글 종류를 전부 대상으로 삼습니다. 고객사마다
 *   이름을 적어 둘 필요가 없고, 새 고객사가 어떤 이름을 쓰든 그대로 됩니다.
 *
 *   여기에 더해 rank_math/json_ld 필터로 스키마(JSON-LD)를 주입합니다.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Notion_Publish_Bridge {

	const VERSION = '1.2.0';

	const NS = 'notion-bridge/v1';

	/** 노션 페이지 ID를 담아두는 메타 키. 중복 발행 방지용. */
	const NOTION_ID_META = '_notion_page_id';

	/** schema_mode=jsonld 일 때 원본 JSON-LD를 담아두는 메타 키. */
	const JSONLD_META = '_notion_jsonld';

	/**
	 * 이 플러그인이 다룰 글 종류.
	 *
	 * 일반 글만 쓰는 고객사가 대부분이지만, 개발사가 '용어사전' 같은 별도 글
	 * 종류를 만들어 둔 사이트가 있습니다(비컴성형외과 glossary). 겉보기 메뉴는
	 * 같아도 속은 다른 글 종류라, 일반 글만 보면 찾지도 기입하지도 못합니다.
	 *
	 * 그래서 고객사마다 이름을 적어 두는 대신, **REST 에 노출된 글 종류를 전부**
	 * 대상으로 삼습니다. 새 고객사가 어떤 이름을 쓰든 손댈 것이 없습니다.
	 * 화면을 만드는 내부 종류(메뉴·템플릿·패턴 등)는 제외합니다.
	 */
	public static function target_post_types() {
		$skip = array(
			'attachment', 'nav_menu_item', 'wp_block', 'wp_template',
			'wp_template_part', 'wp_global_styles', 'wp_navigation',
			'wp_font_family', 'wp_font_face', 'rm_content_editor',
			'rank_math_schema', 'page',
		);

		$types = get_post_types( array( 'show_in_rest' => true ), 'names' );
		$types = array_values( array_diff( $types, $skip ) );

		/**
		 * 이 목록을 사이트에서 바꿔야 할 일이 생기면 이 필터를 씁니다.
		 * 보통은 손댈 일이 없습니다.
		 */
		return apply_filters( 'notion_bridge/post_types', $types );
	}

	public static function init() {
		add_action( 'init', array( __CLASS__, 'register_meta' ) );
		add_action( 'rest_api_init', array( __CLASS__, 'register_routes' ) );
		add_filter( 'rank_math/json_ld', array( __CLASS__, 'inject_jsonld' ), 99, 2 );

		// 코어의 응용 프로그램 비밀번호 검사(우선순위 20)보다 **먼저** 끼어들어,
		// 서버가 지워 버린 자격 증명을 코어가 보는 자리에 되돌려 놓습니다.
		add_filter( 'determine_current_user', array( __CLASS__, 'restore_basic_auth' ), 15 );
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

		foreach ( self::target_post_types() as $post_type ) {
			foreach ( $scalar_keys as $key ) {
				register_post_meta(
					$post_type,
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

		// 진단용. 로그인이 안 될 때 원인을 가르기 위한 것이라 인증을 요구하지
		// 않습니다. 대신 **값은 하나도 돌려주지 않습니다** — 어떤 인증 헤더가
		// PHP까지 닿았는지, 지금 로그인으로 인정됐는지만 알려줍니다.
		register_rest_route(
			self::NS,
			'/auth-probe',
			array(
				'methods'             => 'GET',
				'callback'            => array( __CLASS__, 'handle_auth_probe' ),
				'permission_callback' => '__return_true',
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

	/**
	 * 서버가 Authorization 헤더를 지우는 경우를 메웁니다.
	 *
	 * 워드프레스 코어는 `$_SERVER['PHP_AUTH_USER']` 와 `PHP_AUTH_PW` 가 둘 다
	 * 있을 때만 응용 프로그램 비밀번호를 확인합니다. 일부 서버(LiteSpeed/CGI
	 * 구성, 보안 모듈을 얹은 곳)는 Authorization 헤더를 PHP까지 넘기지 않아
	 * 그 두 값이 비고, 비밀번호가 맞아도 무조건 'rest_not_logged_in' 이 납니다.
	 *
	 * 여기서는 헤더가 살아남았을 만한 자리를 차례로 뒤져 그 두 값만 채워 넣습니다.
	 * **비밀번호 검사는 하지 않습니다** — 그건 그대로 코어가 합니다. 그래서
	 * 인증이 느슨해지지 않고, 서버가 헤더를 멀쩡히 넘겨주는 곳에서는 아무 일도
	 * 일어나지 않습니다.
	 */
	public static function restore_basic_auth( $input_user ) {
		if ( ! empty( $input_user ) ) {
			return $input_user;
		}

		// 코어가 이미 볼 수 있는 상태면 손대지 않습니다.
		if ( isset( $_SERVER['PHP_AUTH_USER'], $_SERVER['PHP_AUTH_PW'] ) ) {
			return $input_user;
		}

		$credentials = self::read_basic_credentials();

		if ( $credentials ) {
			$_SERVER['PHP_AUTH_USER'] = $credentials[0];
			$_SERVER['PHP_AUTH_PW']   = $credentials[1];
		}

		return $input_user;
	}

	/**
	 * Basic 자격 증명이 숨어 있을 수 있는 자리들.
	 *
	 * REDIRECT_ 가 붙은 것은 .htaccess 의 rewrite 를 거치면서 아파치가 붙이는
	 * 이름이고, X-Notion-Authorization 은 Authorization 이 통째로 지워지는
	 * 서버를 위해 발행 도구가 같은 값을 한 벌 더 보내는 헤더입니다.
	 */
	public static function auth_header_keys() {
		return array(
			'HTTP_AUTHORIZATION',
			'REDIRECT_HTTP_AUTHORIZATION',
			'REDIRECT_REDIRECT_HTTP_AUTHORIZATION',
			'HTTP_X_NOTION_AUTHORIZATION',
			'REDIRECT_HTTP_X_NOTION_AUTHORIZATION',
			'REDIRECT_REDIRECT_HTTP_X_NOTION_AUTHORIZATION',
		);
	}

	/** 위 자리들에서 `Basic <base64>` 를 찾아 아이디/비밀번호로 가릅니다. */
	private static function read_basic_credentials() {
		$raw = '';

		foreach ( self::auth_header_keys() as $key ) {
			if ( ! empty( $_SERVER[ $key ] ) && is_string( $_SERVER[ $key ] ) ) {
				$raw = $_SERVER[ $key ];
				break;
			}
		}

		// $_SERVER 에는 안 실리고 getallheaders() 에만 잡히는 구성이 있습니다.
		if ( '' === $raw && function_exists( 'getallheaders' ) ) {
			foreach ( (array) getallheaders() as $name => $value ) {
				$name = strtolower( $name );
				if ( 'authorization' === $name || 'x-notion-authorization' === $name ) {
					$raw = (string) $value;
					break;
				}
			}
		}

		if ( 0 !== stripos( $raw, 'basic ' ) ) {
			return null;
		}

		$decoded = base64_decode( substr( $raw, 6 ), true );

		if ( ! is_string( $decoded ) || false === strpos( $decoded, ':' ) ) {
			return null;
		}

		return explode( ':', $decoded, 2 );
	}

	/**
	 * 인증이 왜 안 되는지 가르는 진단.
	 *
	 * 자격 증명이 틀린 것과, 서버가 헤더를 지워 워드프레스가 아무것도 못 받은
	 * 것은 밖에서 보면 응답이 똑같습니다. 이 경로는 값을 빼고 '무엇이 닿았는지'
	 * 만 돌려주므로 둘을 구분할 수 있습니다.
	 */
	public static function handle_auth_probe() {
		$server_keys = array();

		foreach ( self::auth_header_keys() as $key ) {
			if ( ! empty( $_SERVER[ $key ] ) ) {
				$server_keys[] = $key;
			}
		}

		$header_names = array();

		if ( function_exists( 'getallheaders' ) ) {
			foreach ( (array) getallheaders() as $name => $value ) {
				$lower = strtolower( $name );
				if ( 'authorization' === $lower || 0 === strpos( $lower, 'x-notion-' ) ) {
					$header_names[] = $lower;
				}
			}
		}

		return array(
			'ok'                      => true,
			'version'                 => self::VERSION,
			// 값이 아니라 '있었는지'만.
			'php_auth_user'           => isset( $_SERVER['PHP_AUTH_USER'] ),
			'php_auth_pw'             => isset( $_SERVER['PHP_AUTH_PW'] ),
			'server_keys'             => $server_keys,
			'getallheaders'           => $header_names,
			'sapi'                    => PHP_SAPI,
			'is_ssl'                  => is_ssl(),
			'app_passwords_available' => function_exists( 'wp_is_application_passwords_available' )
				? (bool) wp_is_application_passwords_available()
				: null,
			// 이게 true 면 인증까지 끝난 것입니다 — 남은 문제는 권한뿐입니다.
			'logged_in'               => get_current_user_id() > 0,
			'can_edit_posts'          => current_user_can( 'edit_posts' ),
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
		// 이 사이트가 어떤 글 종류와 분류를 쓰는지 함께 알려 줍니다.
		// 고객사마다 구조가 달라, 이것만 봐도 어디에 올려야 하는지 판단됩니다.
		$types = array();
		foreach ( self::target_post_types() as $name ) {
			$object = get_post_type_object( $name );
			if ( ! $object ) {
				continue;
			}
			$types[] = array(
				'name'       => $name,
				'label'      => $object->labels->name,
				'rest_base'  => $object->rest_base ? $object->rest_base : $name,
				'taxonomies' => array_values( get_object_taxonomies( $name ) ),
			);
		}

		return array(
			'ok'               => true,
			'version'          => self::VERSION,
			'rank_math'        => defined( 'RANK_MATH_VERSION' ) ? RANK_MATH_VERSION : null,
			'rank_math_active' => class_exists( 'RankMath' ),
			'post_types'       => $types,
		);
	}

	public static function handle_lookup( WP_REST_Request $request ) {
		$notion_page_id = self::normalize_uuid( $request->get_param( 'notion_page_id' ) );

		$posts = get_posts(
			array(
				// 용어사전 같은 별도 글 종류에 올라간 글도 찾아야 합니다.
				// 일반 글만 뒤지면 같은 원고가 두 번 올라갑니다.
				'post_type'        => self::target_post_types(),
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
			'found'     => true,
			'post_id'   => $post_id,
			'post_type' => get_post_type( $post_id ),
			'status'    => get_post_status( $post_id ),
			'link'      => get_permalink( $post_id ),
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
		if ( ! is_singular( self::target_post_types() ) ) {
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
