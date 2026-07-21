import os
import pandas as pd
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# 기본 설정
# =========================

BOT_TOKEN = "텔레그램_토큰_입력"

CSV_PATH = "tax_question_answer.csv"
CHAT_ID_PATH = "chat_id.txt"

TIMEZONE = ZoneInfo("Asia/Seoul")

# 문제 받을 시간
QUIZ_TIMES = [
    "08:30",
    "17:50",
    "18:00",
    "18:30",
]

# 각 시간마다 받을 문제 수
QUIZ_COUNT_PER_TIME = 1


# =========================
# CSV 읽기 / 저장
# =========================

def read_csv():
    try:
        df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(CSV_PATH, encoding="cp949")

    if "question" not in df.columns or "answer" not in df.columns:
        raise ValueError("CSV에는 question, answer 열이 반드시 있어야 합니다.")

    df = df.dropna(subset=["question", "answer"]).copy()
    df["question"] = df["question"].astype(str).str.strip()
    df["answer"] = df["answer"].astype(str).str.strip()
    df = df[(df["question"] != "") & (df["answer"] != "")]

    if "id" not in df.columns:
        df["id"] = range(1, len(df) + 1)

    for col, default in {
        "wrong_count": 0,
        "correct_count": 0,
        "level": 0,
        "last_review": "",
        "next_review": "",
    }.items():
        if col not in df.columns:
            df[col] = default

    df["id"] = range(1, len(df) + 1)
    df["wrong_count"] = pd.to_numeric(df["wrong_count"], errors="coerce").fillna(0).astype(int)
    df["correct_count"] = pd.to_numeric(df["correct_count"], errors="coerce").fillna(0).astype(int)
    df["level"] = pd.to_numeric(df["level"], errors="coerce").fillna(0).astype(int)
    df["last_review"] = df["last_review"].fillna("").astype(str)
    df["next_review"] = df["next_review"].fillna("").astype(str)

    save_csv(df)
    return df


def save_csv(df):
    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")


def today():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")


# =========================
# chat_id 저장
# =========================

def save_chat_id(chat_id):
    with open(CHAT_ID_PATH, "w", encoding="utf-8") as f:
        f.write(str(chat_id))


def load_chat_id():
    if not os.path.exists(CHAT_ID_PATH):
        return None

    with open(CHAT_ID_PATH, "r", encoding="utf-8") as f:
        value = f.read().strip()

    if not value:
        return None

    return int(value)


# =========================
# 문제 선택
# =========================

def pick_question(exclude_ids=None):
    if exclude_ids is None:
        exclude_ids = set()

    df = read_csv()
    df = df[~df["id"].isin(exclude_ids)].copy()

    if df.empty:
        return None

    due_df = df[(df["next_review"] == "") | (df["next_review"] <= today())].copy()

    if due_df.empty:
        due_df = df.copy()

    weights = (
        due_df["wrong_count"] * 4
        - due_df["correct_count"]
        - due_df["level"]
        + 3
    ).clip(lower=1)

    return due_df.sample(n=1, weights=weights).iloc[0]


def get_question(question_id):
    df = read_csv()
    row = df[df["id"] == question_id]

    if row.empty:
        return None

    return row.iloc[0]


# =========================
# 복습 기록 업데이트
# =========================

def next_review_days(level, is_correct):
    if not is_correct:
        return 1, 0

    new_level = level + 1

    intervals = {
        1: 1,
        2: 3,
        3: 7,
        4: 14,
        5: 30,
        6: 60,
    }

    return intervals.get(new_level, 90), new_level


def update_result(question_id, is_correct):
    df = read_csv()
    idx_list = df.index[df["id"] == question_id].tolist()

    if not idx_list:
        return "해당 문제를 찾지 못했습니다."

    idx = idx_list[0]
    level = int(df.loc[idx, "level"])

    interval, new_level = next_review_days(level, is_correct)

    if is_correct:
        df.loc[idx, "correct_count"] += 1
        df.loc[idx, "level"] = new_level
        result = "✅ 맞힌 문제로 기록했습니다."
    else:
        df.loc[idx, "wrong_count"] += 1
        df.loc[idx, "level"] = new_level
        result = "❌ 틀린 문제로 기록했습니다."

    now = datetime.now(TIMEZONE)
    df.loc[idx, "last_review"] = now.strftime("%Y-%m-%d")
    df.loc[idx, "next_review"] = (now + timedelta(days=interval)).strftime("%Y-%m-%d")

    save_csv(df)

    return (
        f"{result}\n\n"
        f"Q. {df.loc[idx, 'question']}\n\n"
        f"A. {df.loc[idx, 'answer']}\n\n"
        f"현재 레벨: {df.loc[idx, 'level']}\n"
        f"다음 복습일: {df.loc[idx, 'next_review']}"
    )


# =========================
# 메시지 / 버튼
# =========================

def quiz_keyboard(question_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("정답 보기", callback_data=f"show:{question_id}")]
    ])


def answer_keyboard(question_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("맞았다", callback_data=f"correct:{question_id}"),
            InlineKeyboardButton("틀렸다", callback_data=f"wrong:{question_id}"),
        ],
        [InlineKeyboardButton("다른 문제", callback_data="next")]
    ])


def quiz_text(item):
    return (
        "📚 세법 오답 퀴즈\n\n"
        f"문제 ID: {int(item['id'])}\n\n"
        f"Q. {item['question']}\n\n"
        "아래 버튼을 눌러 정답을 확인하세요."
    )


def answer_text(item):
    return (
        "✅ 정답 확인\n\n"
        f"문제 ID: {int(item['id'])}\n\n"
        f"Q. {item['question']}\n\n"
        f"A. {item['answer']}\n\n"
        "맞혔는지 틀렸는지 기록하세요."
    )


# =========================
# 명령어
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)

    await update.message.reply_text(
        "세법 오답봇이 등록되었습니다.\n\n"
        "이제 정해진 시간에 문제가 자동 발송됩니다.\n\n"
        "/quiz : 지금 문제 받기\n"
        "/stats : 복습 현황 보기"
    )


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)

    item = pick_question()

    if item is None:
        await update.message.reply_text("출제할 문제가 없습니다.")
        return

    await update.message.reply_text(
        quiz_text(item),
        reply_markup=quiz_keyboard(int(item["id"]))
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)

    df = read_csv()

    total = len(df)
    due = len(df[(df["next_review"] == "") | (df["next_review"] <= today())])
    correct = int(df["correct_count"].sum())
    wrong = int(df["wrong_count"].sum())
    reviews = correct + wrong
    accuracy = round(correct / reviews * 100, 1) if reviews else 0

    await update.message.reply_text(
        "📊 복습 현황\n\n"
        f"전체 문제 수: {total}\n"
        f"오늘 복습 대상: {due}\n"
        f"누적 맞힘: {correct}\n"
        f"누적 틀림: {wrong}\n"
        f"정답률: {accuracy}%"
    )


# =========================
# 버튼 처리
# =========================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "next":
        item = pick_question()

        if item is None:
            await query.edit_message_text("출제할 문제가 없습니다.")
            return

        await query.edit_message_text(
            quiz_text(item),
            reply_markup=quiz_keyboard(int(item["id"]))
        )
        return

    action, question_id_text = data.split(":")
    question_id = int(question_id_text)

    item = get_question(question_id)

    if item is None:
        await query.edit_message_text("해당 문제를 찾지 못했습니다.")
        return

    if action == "show":
        await query.edit_message_text(
            answer_text(item),
            reply_markup=answer_keyboard(question_id)
        )

    elif action == "correct":
        await query.edit_message_text(update_result(question_id, True))

    elif action == "wrong":
        await query.edit_message_text(update_result(question_id, False))


# =========================
# 정해진 시간 자동 발송
# =========================

async def scheduled_quiz(context: ContextTypes.DEFAULT_TYPE):
    chat_id = load_chat_id()

    if chat_id is None:
        print("chat_id.txt가 없습니다. 텔레그램에서 /start 또는 /quiz를 먼저 보내세요.")
        return

    used_ids = set()

    for _ in range(QUIZ_COUNT_PER_TIME):
        item = pick_question(exclude_ids=used_ids)

        if item is None:
            print("출제할 문제가 없습니다.")
            return

        question_id = int(item["id"])
        used_ids.add(question_id)

        await context.bot.send_message(
            chat_id=chat_id,
            text=quiz_text(item),
            reply_markup=quiz_keyboard(question_id)
        )

    print(f"{datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')} 자동 발송 완료")


# =========================
# 실행
# =========================

def main():
    if BOT_TOKEN == "여기에_텔레그램_BOT_TOKEN을_넣으세요":
        raise ValueError("BOT_TOKEN을 실제 텔레그램 봇 토큰으로 바꿔주세요.")

    read_csv()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(button_handler))

    for quiz_time in QUIZ_TIMES:
        hour, minute = map(int, quiz_time.split(":"))

        app.job_queue.run_daily(
            scheduled_quiz,
            time=time(hour=hour, minute=minute, tzinfo=TIMEZONE),
            name=f"quiz_{quiz_time}"
        )

    print("세법 오답봇 실행 중입니다.")
    print(f"CSV 파일: {CSV_PATH}")
    print(f"출제 시간: {', '.join(QUIZ_TIMES)}")
    print(f"각 시간당 문제 수: {QUIZ_COUNT_PER_TIME}")
    print("텔레그램에서 /start 또는 /quiz를 먼저 보내세요.")
    print("종료하려면 Ctrl + C를 누르세요.")

    app.run_polling()


if __name__ == "__main__":
    main()