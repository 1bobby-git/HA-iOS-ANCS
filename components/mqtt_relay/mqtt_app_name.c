#include "mqtt_app_name.h"

#include <stddef.h>
#include <strings.h>

typedef struct {
    const char *app_id;
    const char *display_name;
} mqtt_app_name_entry_t;

static const mqtt_app_name_entry_t APP_NAMES[] = {
    {"com.apple.MobileSMS", "메시지"},
    {"com.apple.Maps", "지도"},
    {"com.apple.Music", "Apple Music"},
    {"com.iwilab.KakaoTalk", "카카오톡"},
    {"com.nhncorp.NaverSearch", "네이버"},
    {"com.nhncorp.NaverMap", "네이버 지도"},
    {"com.nhncorp.NaverWebtoon", "네이버 웹툰"},
    {"net.daum.maps", "카카오맵"},
    {"com.google.Gmail", "Gmail"},
    {"com.google.GoogleMobile", "Google"},
    {"com.google.Maps", "Google 지도"},
    {"com.google.ios.youtube", "YouTube"},
    {"com.google.ios.youtubemusic", "YouTube Music"},
    {"com.google.chrome.ios", "Chrome"},
    {"net.whatsapp.WhatsApp", "WhatsApp"},
    {"net.whatsapp.WhatsAppSMB", "WhatsApp Business"},
    {"com.facebook.Facebook", "Facebook"},
    {"com.facebook.Messenger", "Messenger"},
    {"com.burbn.instagram", "Instagram"},
    {"ph.telegra.Telegraph", "Telegram"},
    {"com.atebits.Tweetie2", "X"},
    {"com.spotify.client", "Spotify"},
    {"com.netflix.Netflix", "Netflix"},
    {"com.hammerandchisel.discord", "Discord"},
    {"com.microsoft.Office.Outlook", "Outlook"},
    {"com.microsoft.skype.teams", "Microsoft Teams"},
    {"com.microsoft.azureauthenticator", "Microsoft Authenticator"},
    {"com.tinyspeck.chatlyio", "Slack"},
    {"com.slack.slackintune", "Slack for Intune"},
    {"notion.id", "Notion"},
    {"com.cron.calendar", "Notion 캘린더"},
    {"com.openai.chat", "ChatGPT"},
    {"com.tving.iphone001", "TVING"},
    {"com.jawebs.baedal", "배달의민족"},
    {"com.coupang.Coupang", "쿠팡"},
    {"com.coupang.coupang-eats", "쿠팡이츠"},
    {"com.vivarepublica.cash", "토스"},
    {"com.kakaobank.channel", "카카오뱅크"},
    {"com.kakaopay.payapp.store", "카카오페이"},
    {"com.kbstar.kbbank", "KB스타뱅킹"},
    {"com.kbcard.cxh.appcard", "KB Pay"},
    {"com.shinhan.sbank", "신한 슈퍼SOL"},
    {"com.shinhan.sbank2015", "구 신한 SOL뱅크"},
    {"com.wooribank.smart.npib", "우리WON뱅킹"},
    {"com.wooricard.wcard", "우리WON카드"},
    {"com.hanabank.oqf", "하나원큐"},
    {"com.kebhana.hanapush", "구 하나원큐"},
    {"com.samsungCard.samsungCard", "모니모"},
    {"com.shinhancard.MobilePay", "신한 SOL페이"},
    {"com.hyundaicard.hcappcard", "현대카드"},
    {"com.nonghyup.card.NHAllonePay", "NH pay"},
    {"com.nonghyup.newsmartbanking", "NH스마트뱅킹"},
    {"com.naverfin.payapp", "네이버페이"},
    {"com.nhncorp.NaverShopping", "네이버플러스 스토어"},
    {"com.towneers.www", "당근"},
    {"net.quicket.app", "번개장터"},
    {"net.bucketplacet.ohouse", "오늘의집"},
    {"jp.naver.line", "LINE"},
    {"com.ss.iphone.ugc.Ame", "TikTok"},
    {"com.ss.iphone.ugc.tiktok.lite", "TikTok Lite"},
    {"us.zoom.videomeetings", "Zoom Workplace"},
    {"us.zoom.videomeetings4intune", "Zoom Workplace for Intune"},
    {"com.google.Drive", "Google 드라이브"},
    {"com.google.photos", "Google 포토"},
    {"com.google.calendar", "Google 캘린더"},
    {"com.microsoft.skydrive", "OneDrive"},
    {"com.microsoft.msedge", "Microsoft Edge"},
    {"com.getdropbox.Dropbox", "Dropbox"},
    {"com.reddit.Reddit", "Reddit"},
    {"com.linkedin.LinkedIn", "LinkedIn"},
    {"org.whispersystems.signal", "Signal"},
    {"com.tencent.xin", "WeChat"},
    {"com.alipay.iphoneclient", "Alipay"},
    {"com.ubercab.UberClient", "Uber"},
    {"com.ubercab.UberEats", "Uber Eats"},
    {"com.airbnb.app", "Airbnb"},
    {"kr.co.withweb.aboutyeogi", "여기어때"},
    {"kr.co.rememberapp", "리멤버"},
    {"com.github.stormbreaker.prod", "GitHub"},
    {"com.anthropic.claude", "Claude"},
};

const char *mqtt_app_name_lookup(const char *app_id)
{
    if (app_id == NULL || app_id[0] == '\0') {
        return "";
    }
    for (size_t index = 0; index < sizeof(APP_NAMES) / sizeof(APP_NAMES[0]);
         ++index) {
        if (strcasecmp(app_id, APP_NAMES[index].app_id) == 0) {
            return APP_NAMES[index].display_name;
        }
    }
    return app_id;
}
