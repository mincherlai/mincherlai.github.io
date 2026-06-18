# XPSPeak Web (iPad / 브라우저 버전)

데스크톱 `.app`과 **동일한 numpy/scipy 엔진**을 [Pyodide](https://pyodide.org)로
브라우저에서 실행합니다. iPad·Mac·Windows·크롬북 어디서나 Safari/Chrome으로 열면
됩니다. 계산은 전부 기기 안에서 일어나며 데이터는 서버로 전송되지 않습니다.

## 구성 (전부 정적 파일)

```
web/
  index.html              UI 레이아웃 (반응형: iPad 세로 = 스택, 가로 = 좌우 분할)
  app.js                  UI 로직 + Plotly 플롯 + Python 호출
  bridge.py               JS ↔ 엔진 다리 (JSON 문자열로 통신)
  style.css
  xpspeak/                데스크톱과 동일한 엔진 (functions/background/model/fitting/io_*)
  samples/                Demo 데이터 (As 3d, Ag 3d)
  icons/                  PWA / 홈화면 아이콘
  manifest.webmanifest    "홈 화면에 추가" 메타데이터
  sw.js                   서비스워커 (첫 로딩 후 오프라인 동작)
```

Pyodide와 Plotly는 CDN에서 로드됩니다(첫 로딩만 ~15–25MB, 이후 브라우저 캐시).

## 로컬에서 테스트

```bash
cd web
python3 -m http.server 8766
# 브라우저에서 http://localhost:8766
```

## iPad/학생 배포 — 정적 호스팅에 올리기

PWA(홈 화면 추가·오프라인)는 **HTTPS**가 필요합니다. `web/` 폴더를 아무 정적
호스트에 올리면 됩니다. 가장 쉬운 방법들:

- **Netlify Drop**: https://app.netlify.com/drop 에 `web` 폴더를 드래그&드롭 → 즉시 URL 발급
- **Cloudflare Pages / GitHub Pages**: `web/` 내용을 저장소에 올리고 Pages 활성화
- **대학 웹서버**: `web/` 전체를 그대로 업로드

학생 사용법:
1. 발급된 URL을 iPad Safari로 연다 (첫 로딩 시 엔진 다운로드 — 잠시 대기)
2. 공유 버튼 ▸ **"홈 화면에 추가"** → 앱 아이콘처럼 전체화면 실행
3. 한 번 로딩하면 이후 오프라인에서도 열림

> ⚠️ 서버 호스팅은 외부 게시 행위이므로, 어디에 올릴지는 교수님이 직접 선택/진행해
> 주세요. 이 저장소에는 정적 파일만 준비되어 있습니다.

## 기능 (데스크톱과 동일)

Import(ASCII/Phi/Leybold/VAMAS/Kratos) · 배경(None/Linear/Shirley/Shirley+Linear/
Tougaard) · 피크 s/p/d/f doublet · GL sum/product · Optimize peak/region/all ·
Export(.DAT/.PAR) · 네이티브 저장(.xpsj). 터치로 확대/이동(핀치·드래그) 지원.
