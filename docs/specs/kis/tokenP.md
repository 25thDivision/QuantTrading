# 접근토큰발급(P) - 인증-001

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "접근토큰발급(P)")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: OAuth인증
- API 명: 접근토큰발급(P)
- API ID: 인증-001
- 실전 TR_ID: 
- 모의 TR_ID: 
- HTTP Method: POST
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: https://openapivts.koreainvestment.com:29443
- URL 명: /oauth2/tokenP

### 개요
> 본인 계좌에 필요한 인증 절차로, 인증을 통해 접근 토큰을 부여받아 오픈API 활용이 가능합니다.
>
> 1. 접근토큰(access_token)의 유효기간은 24시간 이며(1일 1회발급 원칙) 
>    갱신발급주기는 6시간 입니다.(6시간 이내는 기존 발급키로 응답)
>
> 2. 접근토큰발급(/oauth2/tokenP) 시 접근토큰값(access_token)과 함께 수신되는 
>    접근토큰 유효기간(acess_token_token_expired)을 이용해 접근토큰을 관리하실 수 있습니다.
>
>
> [참고]
>
> '23.4.28 이후 지나치게 잦은 토큰 발급 요청건을 제어 하기 위해 신규 접근토큰발급 이후 일정시간 이내에 재호출 시에는 직전 토큰값을 리턴하게 되었습니다. 일정시간 이후 접근토큰발급 API 호출 시에는 신규 토큰값을 리턴합니다. 
> 접근토큰발급 API 호출 및 코드 작성하실 때 해당 사항을 참고하시길 바랍니다.
>
> ※ 참고 : 포럼 &gt; 공지사항 &gt;  [수정] [중요] 접근 토큰 발급 변경 안내

### Layout

#### Request Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| grant_type | 권한부여 Type | string | Y | 18 | client_credentials |
| appkey | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| appsecret | 앱시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appsecret (절대 노출되지 않도록 주의해주세요.) |

#### Response Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| access_token | 접근토큰 | string | Y | 350 | OAuth 토큰이 필요한 API 경우 발급한 Access token<br>ex) "eyJ0eXUxMiJ9.eyJz…..................................."<br><br> - 일반개인고객/일반법인고객<br>  . Access token 유효기간 1일<br>  .. 일정시간(6시간) 이내에 재호출 시에는 직전 토큰값을 리턴<br>  . OAuth 2.0의 Client Credentials Grant 절차를 준용<br><br> - 제휴법인<br>  . Access token 유효기간 3개월<br>  . Refresh token 유효기간 1년<br>  . OAuth 2.0의 Authorization Code Grant 절차를 준용 |
| token_type | 접근토큰유형 | string | Y | 20 | 접근토큰유형 : "Bearer"<br>※ API 호출 시, 접근토큰유형 "Bearer" 입력. ex) "Bearer eyJ...." |
| expires_in | 접근토큰 유효기간 | number | Y | 10 | 유효기간(초)<br>ex) 7776000 |
| access_token_token_expired | 접근토큰 유효기간(일시표시) | string | Y | 50 | 유효기간(년:월:일 시:분:초)<br>ex) "2022-08-30 08:10:10" |

### Example
#### Request Example (Python)
```
{
  "grant_type": "client_credentials",
  "appkey": "PSg5dctL9dKPo727J13Ur405OSXXXXXXXXXX",
  "appsecret":  "yo2t8zS68zpdjGuWvFyM9VikjXE0i0CbgPEamnqPA00G0bIfrdfQb2RUD1xP7SqatQXr1cD1fGUNsb78MMXoq6o4lAYt9YTtHAjbMoFy+c72kbq5owQY1Pvp39/x6ejpJlXCj7gE3yVOB/h25Hvl+URmYeBTfrQeOqIAOYc/OIXXXXXXXXXX"
}
```
#### Response Example
```
{
	"access_token":"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ0b2tlbiIsImF1ZCI6ImMwNzM1NTYzLTA1MjctNDNhZS05ODRiLTJiNWI1ZWZmOWYyMyIsImlzcyI6InVub2d3IiwiZXhwIjoxNjQ5NzUxMTAwLCJpYXQiOjE2NDE5NzUxMDAsImp0aSI6IkJTZlM0QUtSSnpRVGpmdHRtdXZlenVQUTlKajc3cHZGdjBZVyJ9.Oyt_C639yUjWmRhymlszgt6jDo8fvIKkkxH1mMngunV1T15SCC4I3Xe6MXxcY23DXunzBfR1uI0KXXXXXXXXXX",
	"access_token_token_expired":"2023-12-22 08:16:59",
	"token_type":"Bearer",
	"expires_in":86400
}
```

## 프로젝트 주석 (명세 아님)
- 용도: 모든 REST 호출의 접근토큰. 어댑터(`quant_trading/broker/kis_quote.py`)가 발급하고 `data/kis_token_<env>.json`에 캐시
- 실측(2026-09-14·28, DECISIONS.md 결정 8): 토큰 24시간 유효, 6시간 내 재요청 시 동일 토큰 반환, 발급 1분 1회. 같은 앱키를 두 머신에서 써도 토큰은 앱키 단위로 동일하게 반환되며 상호 무효화 없음. 초당 호출 한도는 앱키 단위 합산
- 문서의 authorization 설명(유효기간 1일)은 실측 24시간과 일치
