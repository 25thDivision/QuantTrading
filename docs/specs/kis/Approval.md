# 실시간 (웹소켓) 접속키 발급 - 실시간-000

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "실시간 (웹소켓) 접속키 발급")

### 기본정보
- API 통신방식: WEBSOCKET
- 메뉴 위치: OAuth인증
- API 명: 실시간 (웹소켓) 접속키 발급
- API ID: 실시간-000
- 실전 TR_ID: 
- 모의 TR_ID: 
- HTTP Method: POST
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: https://openapivts.koreainvestment.com:29443
- URL 명: /oauth2/Approval

### 개요
> 실시간 (웹소켓) 접속키 발급받으실 수 있는 API 입니다.
> 웹소켓 이용 시 해당 키를 appkey와 appsecret 대신 헤더에 넣어 API를 호출합니다.
>
> 접속키의 유효기간은 24시간이지만, 접속키는 세션 연결 시 초기 1회만 사용하기 때문에 접속키 인증 후에는 세션종료되지 않는 이상 접속키 신규 발급받지 않으셔도 365일 내내 웹소켓 데이터 수신하실 수 있습니다.
>

### Layout

#### Request Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | N | 20 | application/json; utf-8 |

#### Request Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| grant_type | 권한부여타입 | string | Y | 18 | "client_credentials" |
| appkey | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| secretkey | 시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appsecret (절대 노출되지 않도록 주의해주세요.)<br>* 주의 : appsecret와 secretkey는 동일하오니 착오없으시기 바랍니다. (용어가 다른점 양해 부탁드립니다.) |

#### Response Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| approval_key | 웹소켓 접속키 | string | Y | 286 | 웹소켓 이용 시 발급받은 웹소켓 접속키를 appkey와 appsecret 대신 헤더에 넣어 API 호출합니다. |

### Example
#### Request Example (Python)
```
{
	"grant_type": "client_credentials",
	"appkey": "PSg5dctL9dKPo727J13Ur405OSXXXXXXXXXX",
	"secretkey": "yo2t8zS68zpdjGuWvFyM9VikjXE0i0CbgPEamnqPA00G0bIfrdfQb2RUD1xP7SqatQXr1cD1fGUNsb78MMXoq6o4lAYt9YTtHAjbMoFy+c72kbq5owQY1Pvp39/x6ejpJlXCj7gE3yVOB/h25Hvl+URmYeBTfrQeOqIAOYc/OIXXXXXXXXXX"
}
```
#### Response Example
```
{
    "approval_key": "a2585daf-8c09-4587-9fce-8ab893XXXXX"
}
```

## 프로젝트 주석 (명세 아님)
- 용도: 실시간 엔진(Phase 4~5)의 웹소켓 접속키. 실측(결정 11): 웹소켓 구독 41건/앱키, 앱키당 1세션
- 현재 미사용. 데이터 축적은 REST 스윕이 전담하고 웹소켓은 장중 감시 전용 (결정 11)
