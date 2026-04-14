"""
notifier.py — Trade Notification System (V5.4)

Islem gerceklestiginde e-posta bildirimi gonderir.
Gmail SMTP kullanir (App Password gerekli).
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)
_env_vals = dotenv_values(_env_path)

def _get(key): return os.getenv(key) or _env_vals.get(key, "")


def is_enabled() -> bool:
    return bool(_get("SMTP_PASSWORD") and _get("NOTIFY_EMAIL"))


def send_trade_notification(
    action: str,
    ticker: str,
    qty: int,
    price: float,
    confidence: int,
    reasoning: str = "",
    audit_verdict: str = "APPROVE",
    stop_loss: str = "",
    take_profit: str = "",
    risk_pct: float = 0,
):
    """Islem gerceklestiginde e-posta gonder."""
    if not is_enabled():
        print("[Notifier] SMTP_PASSWORD veya NOTIFY_EMAIL tanimli degil, bildirim atladiyor")
        return

    to_email = _get("NOTIFY_EMAIL")
    smtp_email = _get("SMTP_EMAIL") or to_email
    smtp_password = _get("SMTP_PASSWORD")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Emoji ve renk
    action_upper = action.upper()
    if action_upper in ("LONG", "BUY"):
        icon = "BUY"
        color = "#22c55e"
    elif action_upper in ("SHORT", "SELL"):
        icon = "SELL"
        color = "#ef4444"
    elif "CLOSE" in action_upper:
        icon = "CLOSE"
        color = "#f59e0b"
    else:
        icon = action_upper
        color = "#3b82f6"

    subject = f"[Meridian Capital] {icon} {ticker} x{qty} @ ${price:.2f}"

    html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 500px; margin: 0 auto; background: #0a0e17; color: #e2e8f0; border-radius: 12px; overflow: hidden; border: 1px solid #1e293b;">
        <div style="background: {color}; padding: 16px 24px;">
            <h2 style="margin: 0; color: white; font-size: 18px;">{icon} {ticker}</h2>
            <p style="margin: 4px 0 0; color: rgba(255,255,255,0.85); font-size: 13px;">{now}</p>
        </div>
        <div style="padding: 24px;">
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <tr>
                    <td style="padding: 8px 0; color: #94a3b8;">Action</td>
                    <td style="padding: 8px 0; text-align: right; font-weight: 600; color: {color};">{action_upper}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #94a3b8;">Quantity</td>
                    <td style="padding: 8px 0; text-align: right; color: #e2e8f0;">{qty} shares</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #94a3b8;">Price</td>
                    <td style="padding: 8px 0; text-align: right; color: #e2e8f0;">${price:.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #94a3b8;">Total Value</td>
                    <td style="padding: 8px 0; text-align: right; color: #e2e8f0;">${qty * price:,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #94a3b8;">Confidence</td>
                    <td style="padding: 8px 0; text-align: right; color: #e2e8f0;">{confidence}/10</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #94a3b8;">Stop Loss</td>
                    <td style="padding: 8px 0; text-align: right; color: #ef4444;">{stop_loss or 'N/A'}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #94a3b8;">Take Profit</td>
                    <td style="padding: 8px 0; text-align: right; color: #22c55e;">{take_profit or 'N/A'}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #94a3b8;">Risk</td>
                    <td style="padding: 8px 0; text-align: right; color: #e2e8f0;">{risk_pct:.1f}%</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #94a3b8;">Council</td>
                    <td style="padding: 8px 0; text-align: right; color: {'#22c55e' if audit_verdict == 'APPROVE' else '#f59e0b'};">{audit_verdict}</td>
                </tr>
            </table>

            <div style="margin-top: 16px; padding: 12px; background: #111827; border-radius: 8px; border-left: 3px solid {color};">
                <p style="margin: 0; font-size: 12px; color: #94a3b8;">AI Reasoning</p>
                <p style="margin: 6px 0 0; font-size: 13px; color: #cbd5e1; line-height: 1.5;">{reasoning[:300]}</p>
            </div>

            <p style="margin-top: 20px; font-size: 11px; color: #475569; text-align: center;">
                Meridian Capital AI Trading Terminal — Autonomous Mode
            </p>
        </div>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_email
    msg["To"] = to_email

    # Plain text fallback
    plain = f"{icon} {ticker}\n{action_upper} {qty} shares @ ${price:.2f}\nConfidence: {confidence}/10\nCouncil: {audit_verdict}\n\n{reasoning[:200]}"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    _send_email(smtp_email, smtp_password, to_email, msg)
    print(f"[Notifier] E-posta gonderildi: {subject}")


def _send_email(smtp_email, smtp_password, to_email, msg):
    """Gmail SMTP ile e-posta gonder. SSL ve TLS dener."""
    # Yontem 1: SSL (port 465) — Railway'de daha guvenilir
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg.as_string())
        return
    except Exception as e:
        print(f"[Notifier] SSL (465) basarisiz: {e}")

    # Yontem 2: TLS (port 587) — fallback
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg.as_string())
        return
    except Exception as e:
        print(f"[Notifier] TLS (587) basarisiz: {e}")
        raise e


def send_daily_summary(
    trades_today: list,
    total_pnl: float,
    equity: float,
    regime: str,
):
    """Gun sonu ozet e-postasi."""
    if not is_enabled():
        return

    to_email = _get("NOTIFY_EMAIL")
    smtp_email = _get("SMTP_EMAIL") or to_email
    smtp_password = _get("SMTP_PASSWORD")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    trade_count = len(trades_today)
    pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"
    pnl_sign = "+" if total_pnl >= 0 else ""

    trades_html = ""
    for t in trades_today[:10]:
        trades_html += f"""
        <tr>
            <td style="padding: 6px 8px; color: #e2e8f0;">{t.get('ticker','?')}</td>
            <td style="padding: 6px 8px; color: #e2e8f0;">{t.get('action','?').upper()}</td>
            <td style="padding: 6px 8px; color: #e2e8f0;">{t.get('qty',0)}</td>
            <td style="padding: 6px 8px; color: #e2e8f0;">${t.get('price',0):.2f}</td>
        </tr>"""

    subject = f"[Meridian] Daily Summary — {pnl_sign}${total_pnl:.2f} | {trade_count} trades | {now}"

    html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 500px; margin: 0 auto; background: #0a0e17; color: #e2e8f0; border-radius: 12px; overflow: hidden; border: 1px solid #1e293b;">
        <div style="background: #1e293b; padding: 16px 24px;">
            <h2 style="margin: 0; color: white;">Daily Summary — {now}</h2>
        </div>
        <div style="padding: 24px;">
            <div style="display: flex; gap: 16px; margin-bottom: 20px;">
                <div style="flex: 1; background: #111827; padding: 16px; border-radius: 8px; text-align: center;">
                    <p style="margin: 0; font-size: 12px; color: #94a3b8;">P&L</p>
                    <p style="margin: 4px 0 0; font-size: 22px; font-weight: 700; color: {pnl_color};">{pnl_sign}${total_pnl:.2f}</p>
                </div>
                <div style="flex: 1; background: #111827; padding: 16px; border-radius: 8px; text-align: center;">
                    <p style="margin: 0; font-size: 12px; color: #94a3b8;">Equity</p>
                    <p style="margin: 4px 0 0; font-size: 22px; font-weight: 700; color: #e2e8f0;">${equity:,.0f}</p>
                </div>
            </div>
            <p style="color: #94a3b8; font-size: 13px;">Regime: <strong style="color: #e2e8f0;">{regime}</strong> | Trades: <strong style="color: #e2e8f0;">{trade_count}</strong></p>
            <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 12px;">
                <tr style="border-bottom: 1px solid #1e293b;">
                    <th style="padding: 8px; text-align: left; color: #94a3b8;">Ticker</th>
                    <th style="padding: 8px; text-align: left; color: #94a3b8;">Action</th>
                    <th style="padding: 8px; text-align: left; color: #94a3b8;">Qty</th>
                    <th style="padding: 8px; text-align: left; color: #94a3b8;">Price</th>
                </tr>
                {trades_html}
            </table>
            <p style="margin-top: 20px; font-size: 11px; color: #475569; text-align: center;">Meridian Capital AI Trading Terminal</p>
        </div>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg.attach(MIMEText(f"Daily Summary: {pnl_sign}${total_pnl:.2f} | {trade_count} trades | Equity: ${equity:,.0f}", "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        _send_email(smtp_email, smtp_password, to_email, msg)
        print(f"[Notifier] Gunluk ozet gonderildi: {subject}")
    except Exception as e:
        print(f"[Notifier] Ozet e-posta hatasi: {e}")
