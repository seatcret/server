# 지하철 Seat크릿! 서버 🌟

`.env` 에 다음과 같은 환경 변수를 정의해야 합니다.

* `SECRET_KEY`: [Flask 세션 서명용 키](https://flask.palletsprojects.com/en/master/config/#SECRET_KEY)
* `FIREBASE_PRIVATE_KEY`: Base64로 인코딩 된 [Firebase 서비스 계정 키](https://firebase.google.com/docs/admin/setup)
* `SEOUL_API_KEY`: [서울 열린데이터 광장](http://data.seoul.go.kr/) 에서 발급받은 **실시간 지하철 인증키** (일반 인증키가 아니에요!)
