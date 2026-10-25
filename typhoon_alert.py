import os
import re
import json
import hashlib
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

CWA_API_URL = (
    "https://opendata.cwa.gov.tw/api/v1/rest/datastore/"
    "W-C0034-001"
)
CWA_TY_WARN_DATA_URL = (
    "https://www.cwa.gov.tw/Data/js/typhoon/TY_WARN-Data.js"
)
TAIPEI = ZoneInfo("Asia/Taipei")
STATE_PATH = "data/state.json"


def fetch_text(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TyphoonAlert/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def fetch_json(url):
    return json.loads(fetch_text(url))


LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

def send_line_message(message):
    """將訊息推送到指定的個人 LINE。"""
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")

    if not access_token or not user_id:
        raise SystemExit(
            "缺少 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_USER_ID。"
        )

    payload = json.dumps({
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": message[:5000],
            }
        ],
    }).encode("utf-8")

    request = urllib.request.Request(
        LINE_PUSH_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(f"LINE 推播請求成功，HTTP {response.status}")
    except urllib.error.HTTPError as error:
        print(f"LINE 推播失敗，HTTP {error.code}")
        raise


def parse_sections(description):
    result = {}
    for section in description.get("section", []):
        title = section.get("title", "").strip()
        value = section.get("value", "").strip()
        if title:
            result[title] = value
    return result


def parse_typhoon_info(description):
    result = {}
    for group in description.get("typhoon-info", []):
        for section in group.get("section", []):
            title = section.get("title", "").strip()
            value = section.get("value", "").strip()
            if title:
                result[title] = value
    return result


def parse_next_warning_time(js_text, now=None):
    """從 NoteText 讀取下次預定發布時間，處理跨月及跨年。"""
    if now is None:
        now = datetime.now(TAIPEI)
    else:
        now = now.astimezone(TAIPEI)

    match = re.search(
        r"下次警報預定發布時間為\s*"
        r"(\d{1,2})月(\d{1,2})日(\d{1,2})時(\d{1,2})分?",
        js_text,
    )
    if not match:
        return ""

    month, day, hour, minute = map(int, match.groups())

    # 從今年及明年尋找最接近且尚未到達的時間。
    for year in (now.year, now.year + 1):
        try:
            candidate = datetime(
                year, month, day, hour, minute, tzinfo=TAIPEI
            )
        except ValueError:
            continue
        if candidate >= now:
            return candidate.strftime("%Y-%m-%d %H:%M")

    return ""


def get_current_alert(api_data):
    records = api_data.get("records", {})
    infos = records.get("info", [])
    if not infos:
        return None

    info = next(
        (item for item in infos if item.get("language") == "zh-TW"),
        infos[0],
    )
    description = info.get("description", {})
    sections = parse_sections(description)
    typhoon_info = parse_typhoon_info(description)

    report_number = typhoon_info.get("警報報數", "")
    category = typhoon_info.get("警報類別", "")

    published_at = info.get("effective", "")
    if published_at:
        try:
            published_at = (
                datetime.fromisoformat(published_at)
                .astimezone(TAIPEI)
                .strftime("%Y-%m-%d %H:%M")
            )
        except ValueError:
            pass

    try:
        js_text = fetch_text(CWA_TY_WARN_DATA_URL)
        next_time = parse_next_warning_time(js_text)
        print("下次警報時間解析結果：" + (next_time or "未解析到"))
    
        if not next_time:
            match = re.search(r"NoteText.{0,500}", js_text, re.S)
            print("NoteText 資料片段：" + (match.group(0)[:500] if match else "找不到 NoteText"))
    except Exception as error:
        print(f"讀取下次預定發布時間失敗：{type(error).__name__}")
        next_time = ""

    alert = {
        "title": info.get("headline", ""),
        "published_at": published_at,
        "dynamics": sections.get("颱風動態", ""),
        "warning_areas": sections.get("警戒區域及事項", ""),
        "next_warning_time": next_time,
        "url": info.get("web", ""),
        "report_number": report_number,
        "category": category,
        "identifier": info.get("identifier", ""),
    }

    # 部分資料可能把警戒內容放在其他欄位。
    if not alert["warning_areas"]:
        alert["warning_areas"] = sections.get("注意事項", "")

    return alert


def build_message(alert):
    next_time = alert["next_warning_time"] or "氣象署尚未提供"
    return (
        f"【{alert['title'] or '颱風警報'}】\n"
        f"發布時間：{alert['published_at'] or '未提供'}\n\n"
        f"【颱風動態】\n{alert['dynamics'] or '未提供'}\n\n"
        f"【警戒區域及事項】\n"
        f"{alert['warning_areas'] or '未提供'}\n\n"
        f"下次警報預定發布時間：{next_time}\n\n"
        f"發布網址：{alert['url'] or '未提供'}"
    )


def content_hash(alert):
    fields = (
        "title",
        "published_at",
        "dynamics",
        "warning_areas",
        "next_warning_time",
        "url",
        "category",
    )
    canonical = json.dumps(
        {key: alert.get(key, "") for key in fields},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    temporary_path = STATE_PATH + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temporary_path, STATE_PATH)


def save_state_to_github(state):
    """將通知狀態保存回 GitHub repository。"""
    import base64

    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repository:
        raise RuntimeError("缺少 GITHUB_TOKEN 或 GITHUB_REPOSITORY。")

    api_url = (
        f"https://api.github.com/repos/{repository}"
        f"/contents/{STATE_PATH}"
    )

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 取得檔案目前的 SHA，更新既有檔案時必須提供。
    request = urllib.request.Request(api_url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            file_info = json.loads(response.read().decode("utf-8"))
            sha = file_info["sha"]
    except urllib.error.HTTPError as error:
        if error.code == 404:
            sha = None
        else:
            raise

    content = json.dumps(
        state, ensure_ascii=False, indent=2
    ) + "\n"

    body = {
        "message": "Update typhoon alert notification state",
        "content": base64.b64encode(
            content.encode("utf-8")
        ).decode("ascii"),
    }

    if sha:
        body["sha"] = sha

    request = urllib.request.Request(
        api_url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="PUT",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        print(f"GitHub 狀態保存成功，HTTP {response.status}")


def should_notify(alert, state):
    """判斷新報數、內容變更或首次解除警報是否需要通知。"""
    if not alert:
        return False

    report_number = alert["report_number"]
    category = alert["category"]
    digest = content_hash(alert)

    if not report_number:
        return False

    if category == "END":
        return state.get("last_end_report") != report_number

    return (
        state.get("last_report_number") != report_number
        or state.get("last_content_hash") != digest
    )


def main():
    api_key = os.environ.get("CWA_API_KEY")
    if not api_key:
        raise SystemExit("缺少 CWA_API_KEY。")

    query = urllib.parse.urlencode({"Authorization": api_key})
    api_data = fetch_json(f"{CWA_API_URL}?{query}")

    if str(api_data.get("success", "")).lower() != "true":
        raise SystemExit("CWA API 回傳非成功狀態。")

    alert = get_current_alert(api_data)
    if not alert:
        print("目前沒有可解析的颱風警報資料；不通知。")
        return

    state = load_state()

    print("資料解析成功。")
    print(f"警報標題：{alert['title']}")
    print(f"發布時間：{alert['published_at']}")
    print(f"警報報數：{alert['report_number']}")
    print(f"警報類別：{alert['category']}")
    print(f"下次預定發布時間：{alert['next_warning_time'] or '未提供'}")

    report_number = alert["report_number"]
    category = alert["category"]

    if not report_number:
        print("缺少警報報數，為避免錯誤通知，本次略過。")
        return

    if category == "END":
        if state.get("last_end_report") == report_number:
            print("此解除警報已通知過；略過重複通知。")
            return
        print("偵測到解除警報，準備傳送 LINE。")
    else:
        if not should_notify(alert, state):
            print("資料未變更；略過重複通知。")
            return
        print("偵測到新警報或內容變更，準備傳送 LINE。")

    message = build_message(alert)
    print("\n--- LINE 訊息預覽 ---\n")
    print(message)

    # 先傳送 LINE。失敗時會拋出例外，不更新通知狀態。
    send_line_message(message)

    # 只有推播成功後才更新狀態。
    if category == "END":
        state["last_end_report"] = report_number
    else:
        state["last_report_number"] = report_number
        state["last_content_hash"] = content_hash(alert)

    # 先寫入執行環境，再提交到 GitHub 儲存庫。
    save_state(state)
    save_state_to_github(state)

    print("通知及狀態保存流程完成。")


if __name__ == "__main__":
    main()
