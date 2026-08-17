import os
import sys
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import pandas as pd
import ta

# Logueo en vivo para la consola de Render
sys.stdout.reconfigure(line_buffering=True)

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "TU_TOKEN_AQUI")
# CORREGIDO: Se obtiene la variable desde el entorno o el ID directo como String
CHAT_ID = os.environ.get("CHAT_ID", "6744176738") 
SYMBOL = os.environ.get("SYMBOL", "EURGBP=X")
TIMEZONE = ZoneInfo("America/Panama")

# Parámetros de la Estrategia (RSI + Estocástico)
RSI_PERIOD = 14
RSI_OVERSOLD = 35    
RSI_OVERBOUGHT = 65  

STOCH_PERIOD = 14
STOCH_OVERSOLD = 30
STOCH_OVERBOUGHT = 70

last_processed_timestamp = None

# ==========================================
# 2. SERVIDOR DE SALUD (Health Check 24/7)
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo y funcionando.")

    def log_message(self, format, *args):
        return  # Desactivar logs innecesarios del servidor web

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"🌐 Servidor de mantenimiento en puerto {port}", flush=True)
    server.serve_forever()

# ==========================================
# 3. MÓDULO TELEGRAM
# ==========================================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
})

def send_telegram(message: str):
    """Envía alertas formateadas en HTML a Telegram."""
    if TELEGRAM_TOKEN == "TU_TOKEN_AQUI":
        print("⚠️ [ADVERTENCIA] TELEGRAM_TOKEN no configurado.", flush=True)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        res = session.post(url, data=payload, timeout=10)
        if res.status_code != 200:
            print(f"❌ Error Telegram ({res.status_code}): {res.text}", flush=True)
    except Exception as e:
        print(f"❌ Error de conexión con Telegram: {e}", flush=True)

# ==========================================
# 4. DATOS DE MERCADO (Yahoo Finance)
# ==========================================
def fetch_market_data(symbol: str) -> pd.DataFrame:
    """Obtiene velas M1 (1 minuto) de Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m"
    try:
        res = session.get(url, timeout=10)
        if res.status_code != 200:
            return pd.DataFrame()

        data = res.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return pd.DataFrame()

        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        timestamps = result[0].get("timestamp", [])

        if not timestamps or not quotes:
            return pd.DataFrame()

        df = pd.DataFrame({
            "timestamp": timestamps,
            "high": quotes.get("high", []),
            "low": quotes.get("low", []),
            "close": quotes.get("close", [])
        }).dropna().reset_index(drop=True)

        return df
    except Exception as e:
        print(f"❌ Error descargando datos: {e}", flush=True)
        return pd.DataFrame()

# ==========================================
# 5. LÓGICA DE TRADING Y ALERTAS
# ==========================================
def analyze_market():
    global last_processed_timestamp

    df = fetch_market_data(SYMBOL)
    if len(df) < 20:
        return

    # Indicadores Técnicos
    df['rsi'] = ta.momentum.rsi(close=df['close'], window=RSI_PERIOD)
    df['stoch_k'] = ta.momentum.stoch(
        high=df['high'], low=df['low'], close=df['close'], window=STOCH_PERIOD, smooth_window=3
    )

    # Analizar la última vela cerrada (penúltima fila)
    closed_candle = df.iloc[-2]
    timestamp = closed_candle['timestamp']

    if last_processed_timestamp == timestamp:
        return  # Ya procesamos esta vela
    last_processed_timestamp = timestamp

    rsi_val = closed_candle['rsi']
    stoch_val = closed_candle['stoch_k']
    price = closed_candle['close']
    hora_vela = datetime.fromtimestamp(timestamp, tz=TIMEZONE).strftime("%H:%M:%S")

    # Evaluar condiciones
    signal = None
    if rsi_val <= RSI_OVERSOLD or stoch_val <= STOCH_OVERSOLD:
        signal = "COMPRA (CALL) 🟢"
        emoji = "📈"
    elif rsi_val >= RSI_OVERBOUGHT or stoch_val >= STOCH_OVERBOUGHT:
        signal = "VENTA (PUT) 🔴"
        emoji = "📉"

    if signal:
        msg = (
            f"{emoji} <b>ALERTA DE TRADING M1</b> {emoji}\n\n"
            f"📊 <b>Par:</b> <code>{SYMBOL}</code>\n"
            f"🎯 <b>Señal:</b> <b>{signal}</b>\n"
            f"💵 <b>Precio Cierre:</b> <code>{price:.5f}</code>\n"
            f"📉 <b>RSI:</b> <code>{rsi_val:.2f}</code> | <b>Stoch:</b> <code>{stoch_val:.2f}</code>\n"
            f"⏰ <b>Hora Vela:</b> <code>{hora_vela}</code>"
        )
        send_telegram(msg)
        print(f"[{hora_vela}] Señal enviada: {signal}", flush=True)

# ==========================================
# 6. BUCLE PRINCIPAL
# ==========================================
if __name__ == "__main__":
    print(f"🚀 Iniciando Bot para {SYMBOL}...", flush=True)
    
    # Servidor Web en segundo plano
    threading.Thread(target=start_health_server, daemon=True).start()
    
    # Notificación inicial
    send_telegram(f"🤖 <b>Bot iniciado exitosamente</b>\nMonitoreando <code>{SYMBOL}</code>.")

    while True:
        try:
            analyze_market()
        except Exception as e:
            print(f"⚠️ Error en ejecución: {e}", flush=True)
        time.sleep(5)
