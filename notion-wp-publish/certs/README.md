# 고객사 서버가 빠뜨린 중간 인증서

여기에 `.pem` 파일을 두면 워드프레스로 보내는 요청의 CA 검증에 함께 쓰입니다.
(`src/notionwp/trust.py`)

인증서 사슬을 잘못 설치해 둔 고객사 서버가 있습니다. 중간 인증서를 안 보내거나,
그 자리에 최상위 루트를 넣어 보내는 식입니다. 브라우저는 빠진 조각을 알아서
내려받아 메우기 때문에 멀쩡해 보이지만, 서버끼리 통신하는 프로그램은 그러지
않아 이렇게 실패합니다.

```
SSLCertVerificationError: unable to get local issuer certificate
```

**검증을 끄는 것이 아닙니다.** 사슬의 빠진 칸을 채울 뿐이고 최상위 루트까지
정상적으로 검증됩니다. 신뢰할 수 없는 인증서는 그대로 거부됩니다.

## 넣는 법

1. 어느 인증서가 빠졌는지 확인합니다.

   ```
   openssl s_client -proxy $(echo "$HTTPS_PROXY" | sed 's|http://||;s|/$||') \
     -connect <호스트>:443 -servername <호스트> -showcerts </dev/null \
     | grep -E "^ *[0-9]+ s:|^ *i:"
   ```

   맨 위 인증서의 발급자(`i:`)가 그 아래 줄에 없으면 그 인증서가 빠진 것입니다.

2. 그 인증서를 PEM 형식으로 받아 이 폴더에 둡니다. 파일 이름은 사람이 알아볼 수
   있게 짓습니다(예: `RapidSSL-TLS-RSA-CA-G1.pem`).
3. 확장자는 반드시 `.pem` 이어야 읽힙니다.

## 지금 들어 있는 것

| 파일 | 왜 |
|---|---|
| `RapidSSL-TLS-RSA-CA-G1.pem` | 쉬즈메디병원(`www.shesmedi.co.kr`). 서버가 이 중간 인증서를 안 보내고 그 자리에 최상위 루트(DigiCert Global Root G2)를 넣어 보냅니다. `cacerts.rapidssl.com/RapidSSLTLSRSACAG1.crt` 에서 받아 PEM 으로 바꾼 것이고, 인증서 자체는 2027-11-02 까지 유효합니다. |

## 고객사가 서버를 고치면

이 파일을 그대로 둬도 아무 영향이 없습니다. 지워도 되고, 확실해질 때까지
두셔도 됩니다.
