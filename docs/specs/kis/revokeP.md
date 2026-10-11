# 접근토큰폐기(P) - 인증-002

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "접근토큰폐기(P)")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: OAuth인증
- API 명: 접근토큰폐기(P)
- API ID: 인증-002
- 실전 TR_ID: 
- 모의 TR_ID: 
- HTTP Method: POST
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: https://openapivts.koreainvestment.com:29443
- URL 명: /oauth2/revokeP

### 개요
>  부여받은 접큰토큰을 더 이상 활용하지 않을 때 사용합니다.

### Layout

#### Request Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| appkey | 고객 앱Key | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| appsecret | 고객 앱Secret | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appsecret (절대 노출되지 않도록 주의해주세요.) |
| token | 접근토큰 | string | Y | 286 | OAuth 토큰이 필요한 API 경우 발급한 Access token<br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용)<br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용) |

#### Response Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| code | 응답코드 | string | N | 8 | HTTP 응답코드 |
| message | 응답메세지 | string | N | 450 | 응답메세지 |

### Example
#### Request Example (Python)
```
{
  "appkey" : "PSw2UvBQCpoZFc7nZpIfIrOttmXXXXXXXXXX",
  "appsecret" : "/g84gaZp7W3DJEZhamiTH8ZdJkUJ8603rjo3HcOm5PvIc1YC3YmyJOQoW1H0kNjo4IbHwGUdi3+9oEbH4RKKl8GnEu3n/khxm0OrwHkQur+wbA74fcFXxaUnEbftu0X72Eaw9dEBMuK3rODeeOanrsJ1kZ9oKWykIG04F0nmgdXXXXXXXXXX",
  "token" : "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ0b2tlbiIsImF1ZCI6IjZmNDgxMjBiLTlmMDItNGI5ZS05MGExLTRiNDk2MGM5ZWY2MyIsImlzcyI6InVub2d3IiwiZXhwIjoxNjQzMjg2MDUzLCJpYXQiOjE2NDMxOTk2NTMsImp0aSI6IlBTdzJVdkJRQ3dvWkZhOG5acElmSXJPdHRtZUtLUGZCclNKcyJ9.6Z-UvArobBfXbnpSFbFhd9WPVEM3ZQa5NEpqfmQ6rrZBISCi-P9CEamfVReIduTVYbafF02Pl6EPXXXXXXXXXX"
}
```
#### Response Example
```
{
  "code" : 200,
  "message" : "접근토큰 폐기에 성공하였습니다"
}
```

## 프로젝트 주석 (명세 아님)
- 현재 미사용. 두 머신 동시 사용 시 폐기 연동(한쪽 폐기가 다른 쪽에 미치는 영향)은 미실험 (결정 8)
