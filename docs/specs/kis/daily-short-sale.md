# 국내주식 공매도 일별추이 - 국내주식-134

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "국내주식 공매도 일별추이")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: [국내주식] 시세분석
- API 명: 국내주식 공매도 일별추이
- API ID: 국내주식-134
- 실전 TR_ID: FHPST04830000
- 모의 TR_ID: 모의투자 미지원
- HTTP Method: GET
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: 미지
- URL 명: /uapi/domestic-stock/v1/quotations/daily-short-sale

### Layout

#### Request Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| authorization | 접근토큰 | string | Y | 350 | OAuth 토큰이 필요한 API 경우 발급한 Access token <br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용) <br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용) |
| appkey | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| appsecret | 앱시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| personalseckey | 고객식별키 | string | N | 180 | [법인 필수] 제휴사 회원 관리를 위한 고객식별키 |
| tr_id | 거래ID | string | Y | 13 | FHPST04830000 |
| tr_cont | 연속 거래 여부 | string | N | 1 | tr_cont를 이용한 다음조회 불가 API |
| custtype | 고객 타입 | string | Y | 1 | B : 법인 <br>P : 개인 |
| seq_no | 일련번호 | string | N | 2 | [법인 필수] 001 |
| mac_address | 맥주소 | string | N | 12 | 법인고객 혹은 개인고객의 Mac address 값 |
| phone_number | 핸드폰번호 | string | N | 12 | [법인 필수] 제휴사APP을 사용하는 경우 사용자(회원) 핸드폰번호 <br>ex) 01011112222 (하이픈 등 구분값 제거) |
| ip_addr | 접속 단말 공인 IP | string | N | 12 | [법인 필수] 사용자(회원)의 IP Address |
| gt_uid | Global UID | string | N | 32 | [법인 전용] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함 |

#### Request Query Parameter
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| FID_INPUT_DATE_2 | 입력 날짜2 | string | Y | 10 | ~ 누적 |
| FID_COND_MRKT_DIV_CODE | 조건 시장 분류 코드 | string | Y | 2 | 시장구분코드 (주식 J) |
| FID_INPUT_ISCD | 입력 종목코드 | string | Y | 12 | 종목코드 |
| FID_INPUT_DATE_1 | 입력 날짜1 | string | Y | 10 | 공백시 전체 (기간 ~) |

#### Response Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| tr_id | 거래ID | string | Y | 13 | 요청한 tr_id |
| tr_cont | 연속 거래 여부 | string | N | 1 | tr_cont를 이용한 다음조회 불가 API |
| gt_uid | Global UID | string | N | 32 | [법인 전용] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함 |

#### Response Body
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| rt_cd | 성공 실패 여부 | string | Y | 1 |  |
| msg_cd | 응답코드 | string | Y | 8 |  |
| msg1 | 응답메세지 | string | Y | 80 |  |
| output1 | 응답상세 | object | Y |  |  |
| stck_prpr | 주식 현재가 | string | Y | 10 |  |
| prdy_vrss | 전일 대비 | string | Y | 10 |  |
| prdy_vrss_sign | 전일 대비 부호 | string | Y | 1 |  |
| prdy_ctrt | 전일 대비율 | string | Y | 82 |  |
| acml_vol | 누적 거래량 | string | Y | 18 |  |
| prdy_vol | 전일 거래량 | string | Y | 18 |  |
| output2 | 응답상세 | object array | Y |  | array |
| stck_bsop_date | 주식 영업 일자 | string | Y | 8 |  |
| stck_clpr | 주식 종가 | string | Y | 10 |  |
| prdy_vrss | 전일 대비 | string | Y | 10 |  |
| prdy_vrss_sign | 전일 대비 부호 | string | Y | 1 |  |
| prdy_ctrt | 전일 대비율 | string | Y | 82 |  |
| acml_vol | 누적 거래량 | string | Y | 18 |  |
| stnd_vol_smtn | 기준 거래량 합계 | string | Y | 18 |  |
| ssts_cntg_qty | 공매도 체결 수량 | string | Y | 12 |  |
| ssts_vol_rlim | 공매도 거래량 비중 | string | Y | 62 |  |
| acml_ssts_cntg_qty | 누적 공매도 체결 수량 | string | Y | 13 |  |
| acml_ssts_cntg_qty_rlim | 누적 공매도 체결 수량 비중 | string | Y | 72 |  |
| acml_tr_pbmn | 누적 거래 대금 | string | Y | 18 |  |
| stnd_tr_pbmn_smtn | 기준 거래대금 합계 | string | Y | 18 |  |
| ssts_tr_pbmn | 공매도 거래 대금 | string | Y | 18 |  |
| ssts_tr_pbmn_rlim | 공매도 거래대금 비중 | string | Y | 62 |  |
| acml_ssts_tr_pbmn | 누적 공매도 거래 대금 | string | Y | 19 |  |
| acml_ssts_tr_pbmn_rlim | 누적 공매도 거래 대금 비중 | string | Y | 72 |  |
| stck_oprc | 주식 시가2 | string | Y | 10 |  |
| stck_hgpr | 주식 최고가 | string | Y | 10 |  |
| stck_lwpr | 주식 최저가 | string | Y | 10 |  |
| avrg_prc | 평균가격 | string | Y | 11 |  |

### Example
#### Request Example (Python)
```

```
#### Response Example
```

```

## 프로젝트 주석 (명세 아님)
- 용도: 공매도 거래량·대금 수집(1-후반 묶음). 종목별 호출, 기간 지정. 공매도 잔고 필드는 없음 - 잔고는 타 소스 과제
- 모의투자 미지원. 1회 행 수·기간 폭 제한·제공 기간은 문서에 없음
