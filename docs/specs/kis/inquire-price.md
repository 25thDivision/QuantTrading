# 주식현재가 시세 - v1_국내주식-008

## 명세서 원문 (한국투자증권 오픈API 전체 문서 Excel (2026-10-06 03:00 판), 시트 "주식현재가 시세")

### 기본정보
- API 통신방식: REST
- 메뉴 위치: [국내주식] 기본시세
- API 명: 주식현재가 시세
- API ID: v1_국내주식-008
- 실전 TR_ID: FHKST01010100
- 모의 TR_ID: FHKST01010100
- HTTP Method: GET
- 실전 Domain: https://openapi.koreainvestment.com:9443
- 모의 Domain: https://openapivts.koreainvestment.com:29443
- URL 명: /uapi/domestic-stock/v1/quotations/inquire-price

### 개요
> 주식 현재가 시세 API입니다. 실시간 시세를 원하신다면 웹소켓 API를 활용하세요.
>
> ※ 종목코드 마스터파일 파이썬 정제코드는 한국투자증권 Github 참고 부탁드립니다.
>    https://github.com/koreainvestment/open-trading-api/tree/main/stocks_info

### Layout

#### Request Header
| Element | 한글명 | Type | Required | Length | Description |
|---|---|---|---|---|---|
| content-type | 컨텐츠타입 | string | Y | 40 | application/json; charset=utf-8 |
| authorization | 접근토큰 | string | Y | 350 | OAuth 토큰이 필요한 API 경우 발급한 Access token <br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용) <br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용) |
| appkey | 앱키 | string | Y | 36 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| appsecret | 앱시크릿키 | string | Y | 180 | 한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.) |
| personalseckey | 고객식별키 | string | N | 180 | [법인 필수] 제휴사 회원 관리를 위한 고객식별키 |
| tr_id | 거래ID | string | Y | 13 | FHKST01010100 |
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
| FID_COND_MRKT_DIV_CODE | 조건 시장 분류 코드 | string | Y | 2 | J:KRX, NX:NXT, UN:통합 |
| FID_INPUT_ISCD | 입력 종목코드 | string | Y | 12 | 종목코드 (ex 005930 삼성전자)  // ETN은 종목코드 6자리 앞에 Q 입력 필수 |

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
| output | 응답상세 | object | Y |  |  |
| iscd_stat_cls_code | 종목 상태 구분 코드 | string | Y | 3 | 51 : 관리종목<br>52 : 투자위험<br>53 : 투자경고<br>54 : 투자주의<br>55 : 신용가능<br>57 : 증거금 100%<br>58 : 거래정지<br>59 : 단기과열종목 |
| marg_rate | 증거금 비율 | string | Y | 84 |  |
| rprs_mrkt_kor_name | 대표 시장 한글 명 | string | Y | 40 |  |
| new_hgpr_lwpr_cls_code | 신 고가 저가 구분 코드 | string | Y | 10 |  |
| bstp_kor_isnm | 업종 한글 종목명 | string | Y | 40 |  |
| temp_stop_yn | 임시 정지 여부 | string | Y | 1 |  |
| oprc_rang_cont_yn | 시가 범위 연장 여부 | string | Y | 1 |  |
| clpr_rang_cont_yn | 종가 범위 연장 여부 | string | Y | 1 |  |
| crdt_able_yn | 신용 가능 여부 | string | Y | 1 |  |
| grmn_rate_cls_code | 보증금 비율 구분 코드 | string | Y | 3 |  |
| elw_pblc_yn | ELW 발행 여부 | string | Y | 1 |  |
| stck_prpr | 주식 현재가 | string | Y | 10 |  |
| prdy_vrss | 전일 대비 | string | Y | 10 |  |
| prdy_vrss_sign | 전일 대비 부호 | string | Y | 1 |  |
| prdy_ctrt | 전일 대비율 | string | Y | 82 |  |
| acml_tr_pbmn | 누적 거래 대금 | string | Y | 18 |  |
| acml_vol | 누적 거래량 | string | Y | 18 |  |
| prdy_vrss_vol_rate | 전일 대비 거래량 비율 | string | Y | 84 |  |
| stck_oprc | 주식 시가2 | string | Y | 10 |  |
| stck_hgpr | 주식 최고가 | string | Y | 10 |  |
| stck_lwpr | 주식 최저가 | string | Y | 10 |  |
| stck_mxpr | 주식 상한가 | string | Y | 10 |  |
| stck_llam | 주식 하한가 | string | Y | 10 |  |
| stck_sdpr | 주식 기준가 | string | Y | 10 |  |
| wghn_avrg_stck_prc | 가중 평균 주식 가격 | string | Y | 192 |  |
| hts_frgn_ehrt | HTS 외국인 소진율 | string | Y | 82 |  |
| frgn_ntby_qty | 외국인 순매수 수량 | string | Y | 12 |  |
| pgtr_ntby_qty | 프로그램매매 순매수 수량 | string | Y | 18 |  |
| pvt_scnd_dmrs_prc | 피벗 2차 디저항 가격 | string | Y | 10 |  |
| pvt_frst_dmrs_prc | 피벗 1차 디저항 가격 | string | Y | 10 |  |
| pvt_pont_val | 피벗 포인트 값 | string | Y | 10 |  |
| pvt_frst_dmsp_prc | 피벗 1차 디지지 가격 | string | Y | 10 |  |
| pvt_scnd_dmsp_prc | 피벗 2차 디지지 가격 | string | Y | 10 |  |
| dmrs_val | 디저항 값 | string | Y | 10 |  |
| dmsp_val | 디지지 값 | string | Y | 10 |  |
| cpfn | 자본금 | string | Y | 22 |  |
| rstc_wdth_prc | 제한 폭 가격 | string | Y | 10 |  |
| stck_fcam | 주식 액면가 | string | Y | 11 |  |
| stck_sspr | 주식 대용가 | string | Y | 10 |  |
| aspr_unit | 호가단위 | string | Y | 10 |  |
| hts_deal_qty_unit_val | HTS 매매 수량 단위 값 | string | Y | 10 |  |
| lstn_stcn | 상장 주수 | string | Y | 18 |  |
| hts_avls | HTS 시가총액 | string | Y | 18 |  |
| per | PER | string | Y | 82 |  |
| pbr | PBR | string | Y | 82 |  |
| stac_month | 결산 월 | string | Y | 2 |  |
| vol_tnrt | 거래량 회전율 | string | Y | 82 |  |
| eps | EPS | string | Y | 112 |  |
| bps | BPS | string | Y | 112 |  |
| d250_hgpr | 250일 최고가 | string | Y | 10 |  |
| d250_hgpr_date | 250일 최고가 일자 | string | Y | 8 |  |
| d250_hgpr_vrss_prpr_rate | 250일 최고가 대비 현재가 비율 | string | Y | 84 |  |
| d250_lwpr | 250일 최저가 | string | Y | 10 |  |
| d250_lwpr_date | 250일 최저가 일자 | string | Y | 8 |  |
| d250_lwpr_vrss_prpr_rate | 250일 최저가 대비 현재가 비율 | string | Y | 84 |  |
| stck_dryy_hgpr | 주식 연중 최고가 | string | Y | 10 |  |
| dryy_hgpr_vrss_prpr_rate | 연중 최고가 대비 현재가 비율 | string | Y | 84 |  |
| dryy_hgpr_date | 연중 최고가 일자 | string | Y | 8 |  |
| stck_dryy_lwpr | 주식 연중 최저가 | string | Y | 10 |  |
| dryy_lwpr_vrss_prpr_rate | 연중 최저가 대비 현재가 비율 | string | Y | 84 |  |
| dryy_lwpr_date | 연중 최저가 일자 | string | Y | 8 |  |
| w52_hgpr | 52주일 최고가 | string | Y | 10 |  |
| w52_hgpr_vrss_prpr_ctrt | 52주일 최고가 대비 현재가 대비 | string | Y | 82 |  |
| w52_hgpr_date | 52주일 최고가 일자 | string | Y | 8 |  |
| w52_lwpr | 52주일 최저가 | string | Y | 10 |  |
| w52_lwpr_vrss_prpr_ctrt | 52주일 최저가 대비 현재가 대비 | string | Y | 82 |  |
| w52_lwpr_date | 52주일 최저가 일자 | string | Y | 8 |  |
| whol_loan_rmnd_rate | 전체 융자 잔고 비율 | string | Y | 84 |  |
| ssts_yn | 공매도가능여부 | string | Y | 1 |  |
| stck_shrn_iscd | 주식 단축 종목코드 | string | Y | 9 |  |
| fcam_cnnm | 액면가 통화명 | string | Y | 20 |  |
| cpfn_cnnm | 자본금 통화명 | string | Y | 20 |  |
| apprch_rate | 접근도 | string | Y | 112 |  |
| frgn_hldn_qty | 외국인 보유 수량 | string | Y | 18 |  |
| vi_cls_code | VI적용구분코드 | string | Y | 1 |  |
| ovtm_vi_cls_code | 시간외단일가VI적용구분코드 | string | Y | 1 |  |
| last_ssts_cntg_qty | 최종 공매도 체결 수량 | string | Y | 12 |  |
| invt_caful_yn | 투자유의여부 | string | Y | 1 |  |
| mrkt_warn_cls_code | 시장경고코드 | string | Y | 2 |  |
| short_over_yn | 단기과열여부 | string | Y | 1 |  |
| sltr_yn | 정리매매여부 | string | Y | 1 |  |
| mang_issu_cls_code | 관리종목여부 | string | Y | 1 |  |

### Example
#### Request Example (Python)
```
{
"fid_cond_mrkt_div_code": "J",
"fid_input_iscd": "000660"
}
```
#### Response Example
```
{
  "output": {
    "iscd_stat_cls_code": "55",
    "marg_rate": "20.00",
    "rprs_mrkt_kor_name": "KOSPI200",
    "bstp_kor_isnm": "전기.전자",
    "temp_stop_yn": "N",
    "oprc_rang_cont_yn": "N",
    "clpr_rang_cont_yn": "N",
    "crdt_able_yn": "Y",
    "grmn_rate_cls_code": "40",
    "elw_pblc_yn": "Y",
    "stck_prpr": "128500",
    "prdy_vrss": "0",
    "prdy_vrss_sign": "3",
    "prdy_ctrt": "0.00",
    "acml_tr_pbmn": "344570137500",
    "acml_vol": "2669075",
    "prdy_vrss_vol_rate": "75.14",
    "stck_oprc": "128500",
    "stck_hgpr": "130000",
    "stck_lwpr": "128500",
    "stck_mxpr": "167000",
    "stck_llam": "90000",
    "stck_sdpr": "128500",
    "wghn_avrg_stck_prc": "129097.23",
    "hts_frgn_ehrt": "49.48",
    "frgn_ntby_qty": "0",
    "pgtr_ntby_qty": "287715",
    "pvt_scnd_dmrs_prc": "131833",
    "pvt_frst_dmrs_prc": "130166",
    "pvt_pont_val": "128333",
    "pvt_frst_dmsp_prc": "126666",
    "pvt_scnd_dmsp_prc": "124833",
    "dmrs_val": "129250",
    "dmsp_val": "125750",
    "cpfn": "36577",
    "rstc_wdth_prc": "38500",
    "stck_fcam": "5000",
    "stck_sspr": "97660",
    "aspr_unit": "500",
    "hts_deal_qty_unit_val": "1",
    "lstn_stcn": "728002365",
    "hts_avls": "935483",
    "per": "19.67",
    "pbr": "1.72",
    "stac_month": "12",
    "vol_tnrt": "0.37",
    "eps": "6532.00",
    "bps": "74721.00",
    "d250_hgpr": "149500",
    "d250_hgpr_date": "20210225",
    "d250_hgpr_vrss_prpr_rate": "-14.05",
    "d250_lwpr": "90500",
    "d250_lwpr_date": "20211013",
    "d250_lwpr_vrss_prpr_rate": "41.99",
    "stck_dryy_hgpr": "132500",
    "dryy_hgpr_vrss_prpr_rate": "-3.02",
    "dryy_hgpr_date": "20220103",
    "stck_dryy_lwpr": "121500",
... (이하 생략, 26줄 - 원본 Excel 시트 참조)
```

## 프로젝트 주석 (명세 아님)
- 용도: 어댑터의 현재가 조회(실험·진단용). 모의투자 지원
- 지정내역 관련 필드(iscd_stat_cls_code, mrkt_warn_cls_code, mang_issu_cls_code, sltr_yn, short_over_yn, temp_stop_yn 등)가 있으나 종목별 호출이라 전 종목 순회 비용(2,000여 호출/일)이 든다. 지정내역 1차 소스는 종목정보파일 플래그(결정 35). 코드 값 의미가 종목정보파일 헤더(00~03)와 같은지는 미확인
