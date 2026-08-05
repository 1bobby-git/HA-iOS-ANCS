# iOS 알림 앱 ID 참고 목록

ESP32가 ANCS 알림에서 받는 `app_id`는 iOS 앱의 bundle identifier입니다.
펌웨어는 아래 ID를 `앱 이름` 센서의 한글 표시명으로 변환합니다. 이 목록은
완전한 iOS 앱 카탈로그가 아니며, 앱 개발사가 bundle ID를 바꾸거나 별도 앱을
출시하면 달라질 수 있습니다.

목록에 없는 ID는 버리지 않고 원래 `app_id`를 그대로 표시합니다. 실제 알림의
원본 ID는 항상 `최근 알림` 센서 속성에서 확인할 수 있습니다.

## 현재 포함된 대표 매핑

| 앱 ID | 표시 이름 | 확인 기준 |
| --- | --- | --- |
| `com.apple.MobileSMS` | 메시지 | 실제 ANCS 수신값 |
| `com.apple.Maps` | 지도 | Apple App Store 검색 API |
| `com.apple.Music` | Apple Music | Apple App Store 검색 API |
| `com.iwilab.KakaoTalk` | 카카오톡 | Apple App Store 검색 API |
| `com.nhncorp.NaverSearch` | 네이버 | Apple App Store 검색 API |
| `com.nhncorp.NaverMap` | 네이버 지도 | Apple App Store 검색 API |
| `com.nhncorp.NaverWebtoon` | 네이버 웹툰 | Apple App Store 검색 API |
| `net.daum.maps` | 카카오맵 | Apple App Store 검색 API |
| `com.google.Gmail` | Gmail | Apple App Store 검색 API |
| `com.google.GoogleMobile` | Google | Apple App Store 검색 API |
| `com.google.Maps` | Google 지도 | Apple App Store 검색 API |
| `com.google.ios.youtube` | YouTube | Apple App Store 검색 API |
| `com.google.ios.youtubemusic` | YouTube Music | Apple App Store 검색 API |
| `com.google.chrome.ios` | Chrome | Apple App Store 검색 API |
| `net.whatsapp.WhatsApp` | WhatsApp | Apple App Store 검색 API |
| `net.whatsapp.WhatsAppSMB` | WhatsApp Business | Apple App Store 검색 API |
| `com.facebook.Facebook` | Facebook | Apple App Store 검색 API |
| `com.facebook.Messenger` | Messenger | Apple App Store 검색 API |
| `com.burbn.instagram` | Instagram | Apple App Store 검색 API |
| `ph.telegra.Telegraph` | Telegram | Apple App Store 검색 API |
| `com.atebits.Tweetie2` | X | Apple App Store 검색 API |
| `com.spotify.client` | Spotify | Apple App Store 검색 API |
| `com.netflix.Netflix` | Netflix | Apple App Store 검색 API |
| `com.hammerandchisel.discord` | Discord | Apple App Store 검색 API |
| `com.microsoft.Office.Outlook` | Outlook | Apple App Store 검색 API |
| `com.microsoft.skype.teams` | Microsoft Teams | Apple App Store 검색 API |
| `com.microsoft.azureauthenticator` | Microsoft Authenticator | Apple App Store 검색 API |
| `com.tinyspeck.chatlyio` | Slack | Apple App Store 검색 API |
| `com.slack.slackintune` | Slack for Intune | Apple App Store 검색 API |
| `notion.id` | Notion | Apple App Store 검색 API |
| `com.cron.calendar` | Notion 캘린더 | Apple App Store 검색 API |
| `com.openai.chat` | ChatGPT | Apple App Store 검색 API |
| `com.tving.iphone001` | TVING | Apple App Store 검색 API |
| `com.jawebs.baedal` | 배달의민족 | Apple App Store 검색 API |
| `com.coupang.Coupang` | 쿠팡 | Apple App Store 검색 API |
| `com.coupang.coupang-eats` | 쿠팡이츠 | Apple App Store 검색 API |
| `com.vivarepublica.cash` | 토스 | Apple App Store 검색 API |
| `com.kakaobank.channel` | 카카오뱅크 | Apple App Store 검색 API |
| `com.kakaopay.payapp.store` | 카카오페이 | Apple App Store 검색 API |
| `com.kbstar.kbbank` | KB스타뱅킹 | Apple App Store 검색 API |
| `com.kbcard.cxh.appcard` | KB Pay | Apple App Store 검색 API |
| `com.shinhan.sbank` | 신한 슈퍼SOL | Apple App Store 검색 API |
| `com.shinhan.sbank2015` | 구 신한 SOL뱅크 | Apple App Store 검색 API |
| `com.wooribank.smart.npib` | 우리WON뱅킹 | Apple App Store 검색 API |
| `com.wooricard.wcard` | 우리WON카드 | Apple App Store 검색 API |
| `com.hanabank.oqf` | 하나원큐 | Apple App Store 검색 API |
| `com.kebhana.hanapush` | 구 하나원큐 | Apple App Store 검색 API |
| `com.samsungCard.samsungCard` | 모니모 | Apple App Store 검색 API |
| `com.shinhancard.MobilePay` | 신한 SOL페이 | Apple App Store 검색 API |
| `com.hyundaicard.hcappcard` | 현대카드 | Apple App Store 검색 API |
| `com.nonghyup.card.NHAllonePay` | NH pay | Apple App Store 검색 API |
| `com.nonghyup.newsmartbanking` | NH스마트뱅킹 | Apple App Store 검색 API |
| `com.naverfin.payapp` | 네이버페이 | Apple App Store 검색 API |
| `com.nhncorp.NaverShopping` | 네이버플러스 스토어 | Apple App Store 검색 API |
| `com.towneers.www` | 당근 | Apple App Store 검색 API |
| `net.quicket.app` | 번개장터 | Apple App Store 검색 API |
| `net.bucketplacet.ohouse` | 오늘의집 | Apple App Store 검색 API |
| `jp.naver.line` | LINE | Apple App Store 검색 API |
| `com.ss.iphone.ugc.Ame` | TikTok | Apple App Store 검색 API |
| `com.ss.iphone.ugc.tiktok.lite` | TikTok Lite | Apple App Store 검색 API |
| `us.zoom.videomeetings` | Zoom Workplace | Apple App Store 검색 API |
| `us.zoom.videomeetings4intune` | Zoom Workplace for Intune | Apple App Store 검색 API |
| `com.google.Drive` | Google 드라이브 | Apple App Store 검색 API |
| `com.google.photos` | Google 포토 | Apple App Store 검색 API |
| `com.google.calendar` | Google 캘린더 | Apple App Store 검색 API |
| `com.microsoft.skydrive` | OneDrive | Apple App Store 검색 API |
| `com.microsoft.msedge` | Microsoft Edge | Apple App Store 검색 API |
| `com.getdropbox.Dropbox` | Dropbox | Apple App Store 검색 API |
| `com.reddit.Reddit` | Reddit | Apple App Store 검색 API |
| `com.linkedin.LinkedIn` | LinkedIn | Apple App Store 검색 API |
| `org.whispersystems.signal` | Signal | Apple App Store 검색 API |
| `com.tencent.xin` | WeChat | Apple App Store 검색 API |
| `com.alipay.iphoneclient` | Alipay | Apple App Store 검색 API |
| `com.ubercab.UberClient` | Uber | Apple App Store 검색 API |
| `com.ubercab.UberEats` | Uber Eats | Apple App Store 검색 API |
| `com.airbnb.app` | Airbnb | Apple App Store 검색 API |
| `kr.co.withweb.aboutyeogi` | 여기어때 | Apple App Store 검색 API |
| `kr.co.rememberapp` | 리멤버 | Apple App Store 검색 API |
| `com.github.stormbreaker.prod` | GitHub | Apple App Store 검색 API |
| `com.anthropic.claude` | Claude | Apple App Store 검색 API |

## 확인 및 추가 방법

1. Home Assistant의 `최근 알림` 센서 속성에서 `app_id`를 확인합니다.
2. Apple App Store의 앱과 개발사가 맞는지 확인합니다.
3. 펌웨어의 앱 ID 매핑 테이블과 이 문서를 같은 변경에서 함께 갱신합니다.
4. 정확히 일치하는 ID만 추가하고, 추측한 ID는 추가하지 않습니다.

Apple은 bundle identifier가 앱을 고유하게 식별하며 일반적으로 역방향 DNS
형식을 사용한다고 설명합니다. App Store에 공개된 앱의 확인에는 Apple의
[iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/Searching.html)를
사용합니다.
