"""
Claude 融合脆弱度指標 (FRAGILITY, 不是 TIMING)
讀「現在多脆弱」的可量化訊號 → 0~10 分 + 建議下車區間。明確不預測「何時」。
標的趨勢用該市場; 信用/曲線/金融狀況/廣度是美國=全球風險背景(台股也吃全球 risk-off)。
用法: python fragility_dashboard.py [TICKER]   預設 ^TWII
"""
import sys, io, urllib.request
import numpy as np, pandas as pd, yfinance as yf
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass

args = [a for a in sys.argv[1:] if not a.startswith('--')]
TICKER = args[0] if args else "^TWII"
JSON_OUT = '--json' in sys.argv

def fred(series):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    raw = urllib.request.urlopen(req, timeout=25).read().decode()
    df = pd.read_csv(io.StringIO(raw)); df.columns = ['date', 'val']
    df['val'] = pd.to_numeric(df['val'], errors='coerce'); df = df.dropna()
    df['date'] = pd.to_datetime(df['date']); return df.set_index('date')['val']

def px(tk, period="3y"):
    d = yf.download(tk, period=period, progress=False, auto_adjust=True)
    if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
    return d["Close"].dropna()

def cape():
    import re
    url = "https://www.multpl.com/shiller-pe"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'ignore')
    m = re.search(r'Current Shiller PE Ratio[^0-9]*([0-9]{1,2}\.[0-9]+)', html) or re.search(r'([0-9]{2}\.[0-9]{2})', html)
    return float(m.group(1))

S = []  # (訊號, 讀數, 分, 說明)

# 1. 標的趨勢 / 乖離  (200MA 是我們測過唯一有效的出場訊號)
try:
    c = px(TICKER); ma200 = c.rolling(200).mean(); ma50 = c.rolling(50).mean()
    last, m2, m5 = c.iloc[-1], ma200.iloc[-1], ma50.iloc[-1]
    above = (last / m2 - 1) * 100; pts = 0; note = []
    if last < m2: pts += 2.5; note.append("跌破200MA(主出場訊號)")
    else: note.append(f"在200MA上方+{above:.0f}%")
    if m5 < m2: pts += 1.0; note.append("50<200死叉")
    if above > 60: pts += 2.0; note.append("乖離>60%過熱")
    elif above > 30: pts += 1.0; note.append("乖離>30%")
    S.append((f"{TICKER}趨勢/乖離", f"價{last:.0f}/200MA{m2:.0f}", pts, "; ".join(note)))
except Exception as e: S.append((f"{TICKER}趨勢", "抓取失敗", 0, str(e)[:40]))

# 2. 高收益債信用利差 (信用常領先股市出事)
try:
    hy = fred("BAMLH0A0HYM2"); cur = hy.iloc[-1]; a1 = hy[hy.index >= hy.index[-1]-pd.Timedelta(days=365)].mean()
    chg = cur - hy.asof(hy.index[-1] - pd.Timedelta(days=90)); pts = 0; st = "平靜"
    if cur > a1 * 1.15: pts += 1.0; st = "高於均值"
    if chg > 0.7: pts += 1.0; st = "快速擴大(壓力升)"
    S.append(("HY信用利差", f"{cur:.2f}%(1yr均{a1:.2f})", pts, st))
except Exception as e: S.append(("HY信用利差", "抓取失敗", 0, str(e)[:40]))

# 3. 殖利率曲線 10Y-2Y (著名衰退前兆, 但領先6~24月)
try:
    cv = fred("T10Y2Y"); cur = cv.iloc[-1]; mn = cv[cv.index >= cv.index[-1]-pd.Timedelta(days=400)].min(); pts = 0; st = f"{cur:+.2f}"
    if cur < 0: pts += 0.5; st += " 倒掛"
    if mn < 0 and cur > 0: pts += 1.0; st += " 倒掛後翻正(衰退前段)"
    S.append(("殖利率曲線10Y-2Y", st, pts, "領先6~24月,極不定"))
except Exception as e: S.append(("殖利率曲線", "抓取失敗", 0, str(e)[:40]))

# 4. NFCI 金融狀況 (>0 = 比平均緊 = 壓力)
try:
    n = fred("NFCI"); cur = n.iloc[-1]; pts = 0; st = "寬鬆" if cur < 0 else "偏緊"
    if cur > 0: pts += 1.0
    if cur > 0.5: pts += 0.5; st = "明顯緊縮"
    S.append(("NFCI金融狀況", f"{cur:+.2f}", pts, st))
except Exception as e: S.append(("NFCI金融狀況", "抓取失敗", 0, str(e)[:40]))

# 5. VIX (雙面: 極高常是恐慌底, 只給小權)
try:
    v = fred("VIXCLS"); cur = v.iloc[-1]; pts = 0; st = f"{cur:.1f}"
    if cur > 28: pts += 0.5; st += " 偏高"
    S.append(("VIX波動", st, pts, "雙面:極高常是底"))
except Exception as e: S.append(("VIX波動", "抓取失敗", 0, str(e)[:40]))

# 6. 美股廣度代理 RSP/SPY (等權落後市值權 = 少數權值撐盤)
try:
    rsp = px("RSP", "1y"); spy = px("SPY", "1y"); ratio = (rsp / spy).dropna()
    if len(ratio) > 130:
        chg = (ratio.iloc[-1] / ratio.iloc[-126] - 1) * 100; pts = 1.0 if chg < -3 else 0.0
        S.append(("市場廣度RSP/SPY", f"6月{chg:+.1f}%", pts, "負=廣度差,撐盤"))
except Exception as e: S.append(("市場廣度", "抓取失敗", 0, str(e)[:40]))

# 7. 市場估值 Shiller CAPE (美股=全球估值背景; 歷史均~17)
try:
    pe = cape(); pts = 0; st = f"{pe:.1f}"
    if pe > 35: pts += 2.0; st += " 極貴"
    elif pe > 28: pts += 1.0; st += " 偏貴"
    else: st += " 尚可"
    S.append(("Shiller CAPE估值", st, pts, "歷史均~17; 高估值→長期報酬偏低"))
except Exception as e: S.append(("Shiller CAPE", "抓取失敗", 0, str(e)[:40]))

total = min(10, sum(s[2] for s in S))
print(f"\n=== Claude 融合脆弱度指標   標的:{TICKER} ===")
print(f"{'訊號':<20}{'讀數':<26}{'分':>5}  說明")
print("-" * 90)
for name, reading, pts, note in S:
    print(f"{name:<20}{reading:<26}{pts:>5.1f}  {note}")
print("-" * 90)
print(f"脆弱度總分: {total:.1f} / 10")
band = ("低脆弱 → 留在車上(時間在場內是 edge)" if total < 3 else
        "升高 → 留意, 小幅減碼+拉現金" if total < 5 else
        "明顯 → 減碼+考慮便宜尾端避險" if total < 7 else
        "高 → 大幅下車+關槓桿")
print(f"建議區間: {band}")
print("\n⚠️ 這是『狀態』不是『時點』。脆弱≠馬上爆;領先時間極不定(可能早數月~數年)。")
print("   執行法:分批回應、接受自己會早、機械照表。不預測哪天。")
print("   你的部位%/槓桿請自己加進總分(估值已含 Shiller CAPE)。")

if JSON_OUT:
    import json, datetime
    out = {'ticker': TICKER, 'total': round(total, 1), 'band': band,
           'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
           'signals': [{'name': n, 'reading': r, 'pts': p, 'note': nt} for n, r, p, nt in S]}
    with open('fragility.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('wrote fragility.json')
