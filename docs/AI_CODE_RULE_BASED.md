# 📏 AI Code Rule Based — Development Standards

> **ใช้เป็นข้อบังคับ สำหรับทุกการแก้ไข code ในโปรเจค Deriv AI Bot**
> **ใช้เป็นข้อบังคับ สำหรับทุกการแก้ไข code ในโปรเจค Deriv AI Bot**
> Last Updated: v5.0.0 — 2026-03-03

---

## 1. 📐 Version Numbering (Semantic Versioning)

```
MAJOR.MINOR.PATCH
  │      │      └── Bug fix, config tweak, typo fix
  │      └── New feature, new indicator, new AI provider
  └── Breaking change, architecture rewrite
```

| ตัวอย่าง | ประเภท |
|----------|--------|
| v3.11.x → v3.12.0 | New indicator / strategy logic |
| v3.11.x → v4.0.0 | Architecture rewrite (e.g. Polling to Streaming) |

### Rule: ทุกครั้งที่แก้ไข code ต้อง
1. **Bump version** ในไฟล์ที่แก้ (docstring บรรทัดที่ 2)
2. **Update `BOT_VERSION`** ใน `config.py` (ถ้ามีการแก้ logic)
3. **เพิ่ม entry** ใน `CHANGELOG.md`
4. **Update files** ตาม Doc Update Matrix (Section 5)

---

## 2. 🛡️ File Safety Classification

| ระดับ | ไฟล์ | ใครแก้ได้ | ต้อง review? |
|-------|------|-----------|-------------|
| 🔴 CRITICAL | `bot.py`, `trade_engine.py` | Human only | ✅ Always |
| 🟠 HIGH | `config.py`, `ai_engine.py`, `smart_trader.py`, `stream_manager.py`, `asset_profiles.json` | Human + AI Council (profiles/config only) | ✅ For logic |
| 🟡 MEDIUM | `market_engine.py`, `technical_analysis.py`, `ai_providers.py`, `asset_selector.py` | Human + AI | ⚠️ Recommended |
| 🟢 LOW | `utils.py`, `dashboard_server.py`, `backtest*.py` | Human + AI | Optional |
| 🔒 PROTECTED | `ai_council.py`, `test_ai_council.py` | Human only | ✅ Always |

### AI Council Configuration Strategy (v3.7.5)
- **Council Sandbox Rule**: ทุกการตัดสินใจปรับ parameter ใน `config.py` ต้องกระทำที่ `TIER_COUNCIL` profile เท่านั้น
- **Profile Switching**: AI Council สามารถเปลี่ยน `ACTIVE_PROFILE = "TIER_COUNCIL"` ได้หากต้องการให้การตั้งค่ามีผลทันที
- **ห้ามแก้ Profile อื่น**: ห้ามแก้ไขค่าใน `TIER_MICRO`, `TIER_MINI`, ฯลฯ (ถือเป็น Golden Profiles)
- ห้ามเพิ่ม `AMOUNT` เกิน 5.0 ใน `TIER_COUNCIL`
- ห้ามเพิ่ม `MAX_MARTINGALE_STEPS` เกิน 5
- ห้ามลด `MAX_DAILY_LOSS_PERCENT` หรือ `MAX_DAILY_LOSS_ABSOLUTE` ต่ำกว่าเดิมที่ผู้ใช้ตั้งไว้
- AI Council Restrictions
- `CONSECUTIVE_LOSS` / `NO_TRADE_TIMEOUT` → แก้ได้เฉพาะ `config.py`
- `CODE_ERROR` → แก้ `.py` ใดก็ได้ ยกเว้น PROTECTED

---

## 3. 📝 Coding Standards

### 3.1 Docstring Header (ทุกไฟล์ .py ต้องมี)
```python
"""
<emoji> <Module Name> (v<MAJOR>.<MINOR>.<PATCH>)
<One-line description>
"""
```
**ตัวอย่าง:**
```python
"""
📈 Market Engine (v3.5.1)
Handles market data fetching, candle processing, and technical indicator calculation.
"""
```

### 3.2 Inline Change Tags
เมื่อแก้ logic สำคัญ ต้องใส่ tag:
```python
# [v3.5.1] Added RSI/MACD/ATR to market summary for AI Analyst
```

### 3.3 Type Safety
- ค่าจาก API/Dashboard/State → **ต้อง cast type เสมอ** (`float()`, `int()`, `str()`)
- ใช้ pattern: `float(value or 0.0)` เพื่อป้องกัน None

### 3.4 Error Handling
- ฟังก์ชันที่เรียก external API → ต้องมี `try/except` + timeout
- ห้าม `except:` เปล่า ต้องระบุ exception type หรืออย่างน้อย `except Exception as e:`
- AI provider calls → ต้องมี fallback

### 3.5 Config-First Design
- ห้าม hardcode ตัวเลข magic number → ใช้ `getattr(config, "KEY", default)`
- ค่า threshold ทุกตัวต้องอยู่ใน `config.py`

---

## 4. ✅ Pre-Commit Checklist

ก่อนถือว่าการแก้ไขเสร็จ ต้องผ่านทุกข้อ:

- [ ] `python -m py_compile <file>` ผ่านทุกไฟล์ที่แก้
- [ ] Bump version ใน docstring ของไฟล์ที่แก้
- [ ] เพิ่ม entry ใน `CHANGELOG.md`
- [ ] Update เอกสารตาม **Doc Update Matrix** (Section 5)
- [ ] ถ้าแก้ `config.py` → ตรวจว่า `PROFILES` ยังถูกต้อง
- [ ] ถ้าเพิ่ม indicator → update `FEATURES.md`
- [ ] ถ้าเพิ่มไฟล์ใหม่ → update `PROJECT_MAP.md`

---

## 5. 📚 Doc Update Matrix

> เมื่อแก้ไขประเภทต่างๆ ต้อง update ไฟล์ .md ใดบ้าง

| ประเภทการแก้ไข | CHANGELOG | FEATURES | PROJECT_MAP | README |
|----------------|-----------|----------|-------------|--------|
| Bug fix | ✅ | — | — | — |
| Config change | ✅ | — | — | — |
| New indicator / signal logic | ✅ | ✅ | — | — |
| New AI provider | ✅ | ✅ | ✅ | ✅ |
| New file (.py) | ✅ | — | ✅ | — |
| Delete file (.py) | ✅ | — | ✅ | — |
| Architecture change | ✅ | ✅ | ✅ | ✅ |
| Dashboard UI change | ✅ | — | — | — |
| Security / safety logic | ✅ | ✅ | — | — |
| Performance / timeout tweak | ✅ | — | — | — |

### ตัวอย่างเชิงปฏิบัติ

**เรื่อง 1: แก้ bug ValueError ใน ai_council.py**
→ Update: `CHANGELOG.md` เท่านั้น

**เรื่อง 2: เพิ่ม RSI/MACD ให้ market_engine summary**
→ Update: `CHANGELOG.md` + `FEATURES.md` (เพราะเป็น signal logic ใหม่)

**เรื่อง 3: เพิ่ม AI provider ตัวใหม่ (เช่น Deepseek)**
→ Update: `CHANGELOG.md` + `FEATURES.md` + `PROJECT_MAP.md` + `README.md`

**เรื่อง 4: สร้างไฟล์ backtest_losses.py**
→ Update: `CHANGELOG.md` + `PROJECT_MAP.md`

---

## 6. 🧪 Testing Standards

| ระดับ | เมื่อไหร่ | วิธี |
|-------|----------|------|
| Syntax Check | ทุกครั้ง | `python -m py_compile <file>` |
| Unit Test | แก้ indicator/scoring | `python test_ai_council.py` + เพิ่ม test case |
| Backtest | แก้ signal logic | สร้าง backtest script ทดสอบกับ historical data |
| Live Test | แก้ trade execution | Run bot ใน Practice account 1 ชม. |

---

## 7. 🏛️ AI Council Rules (สำหรับ prompt ของ Council)

### ห้ามทำ (NEVER)
- ❌ เพิ่ม `AMOUNT` ใน PROFILES
- ❌ ลด `MAX_DAILY_LOSS_PERCENT` หรือ `MAX_DAILY_LOSS_ABSOLUTE`
- ❌ เพิ่ม `MAX_MARTINGALE_STEPS`
- ❌ เพิ่ม `MARTINGALE_MULTIPLIER`
- ❌ แก้ `ai_council.py` (self-modification)
- ❌ ลบ safety guard ใดๆ

### ทำได้ (ALLOWED for CONSECUTIVE_LOSS / NO_TRADE_TIMEOUT)
- ✅ ลด `AI_CONFIDENCE_THRESHOLD` (min: 0.50)
- ✅ Toggle `USE_OLLAMA_TREND_FILTER`
- ✅ Toggle `ALLOW_PUT_SIGNALS`
- ✅ เปลี่ยน `ACTIVE_PROFILE`
- ✅ ปรับ `L2_MIN_CONFIRMATION` (min: 0.30)

### ทำได้ (ALLOWED for CODE_ERROR)
- ✅ แก้ไข `.py` ใดก็ได้ ยกเว้น PROTECTED
- ✅ เพิ่ม try/except, type casting
- ✅ แก้ import, syntax error
### ทำได้ (ALLOWED for USER_COMMAND)
- ✅ เปลี่ยน `DERIV_ACCOUNT_TYPE` ระหว่าง `"demo"` และ `"real"` (ต้องมีการสั่งงานโดยตรงจากผู้ใช้เท่านั้น)
- ✅ เปลี่ยน parameter สำคัญอื่นๆ นอกเหนือจาก TIER_COUNCIL (หากมีการระบุเจาะจงโดยผู้ใช้)
- **Consultation Mode:**
  - ℹ️ หากผู้ใช้ถามคำถาม, ขอวิเคราะห์, หรือขอคำแนะนำ (Analysis/QA)
  - ❌ **ห้ามแก้ไข Code เด็ดขาด** (return `changes: []`)
  - ✅ **ต้องตอบเป็นภาษาไทย** (ใช้ทับศัพท์เทคนิคภาษาอังกฤษ)

---

## 8. 📋 Version History of This Document

| Version | Date | Changes |
|---------|------|---------|
| v5.0.0 | 2026-03-03 | Final completion of Adaptive Engine and Profiling system |
| v4.0.0 | 2026-02-23 | Architecture rewrite (Polling to Streaming) |
| v3.10.0 | 2026-02-20 | Added Consultation Mode rules (No Code Changes + Thai Language) |
| v1.0.0 | 2026-02-17 | Initial creation |
