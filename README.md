# 📄 README.md (2 Versions)

ผมจะทำให้ 2 ไฟล์แยกกันครับ:
- `README.md` → ภาษาไทย (สำหรับคนอ่าน, มี context ครบ, อ่านง่าย)
- `README.ai.md` → ภาษาอังกฤษ (สำหรับ AI agent, กระชับ, structured, ประหยัด token)

---

## 📘 Version 1: `README.md` (Thai - For Humans)

```markdown
# 🚚 Route Optimization Engine (ROE)
### ระบบจัดเส้นทางขนส่งอัตโนมัติด้วย AI/Optimization

โปรเจกต์นี้เป็นส่วนหนึ่งของวิชา [ชื่อวิชา] คณะ [ชื่อคณะ]  
สถาบันเทคโนโลยีพระจอมเกล้าเจ้าคุณทหารลาดกระบัง (KMITL)

**สมาชิกทีม:** ขิง (Backend) | อาร์ม (Optimization) | หมิว (Frontend)

---

## 📌 เกี่ยวกับโปรเจกต์นี้

ระบบเว็บแอปพลิเคชันที่ช่วยธุรกิจขนส่งจัดเส้นทางวิ่งรถให้อัตโนมัติ โดยใช้ **CVRPTW (Capacitated Vehicle Routing Problem with Time Windows)** แทนการจัดรถแบบเดิมที่ใช้คนหรือระบบคิว (First-Come, First-Served)

### 🎯 ปัญหาที่แก้ไข
- ❌ การจัดรถแบบเดิมทำให้รถวิ่งข้ามโซนไปมา สิ้นเปลืองน้ำมัน
- ❌ ใช้จำนวนรถเยอะเกินความจำเป็น
- ❌ เสี่ยงส่งสินค้าล่าช้าเพราะไม่ได้คำนึงถึง Time Window

### ✅ วิธีแก้ปัญหา
ใช้ **Google OR-Tools** คำนวณเส้นทางที่เหมาะสมที่สุด โดยพิจารณา 5 ปัจจัยพร้อมกัน:
1. **Time Windows** — ต้องส่งภายในเวลาที่ลูกค้านัด
2. **Vehicle Capacity** — น้ำหนักรวมต้องไม่เกินที่รถรับได้
3. **Distance Minimization** — บีบระยะห่างระหว่างจุดส่งให้สั้นที่สุด
4. **Fleet Optimization** — ใช้จำนวนรถน้อยที่สุด
5. **Guided Local Search** — หลีกเลี่ยงคำตอบที่ติดหลุมพราง (Local Optima)

---

## 🖼️ Demo Screenshot
*(ใส่ภาพหน้าจอเว็บแอปตอนแสดงแผนที่เส้นทาง)*

---

## 🏗️ สถาปัตยกรรมระบบ

```
Frontend (HTML/CSS/JS + Leaflet.js)
        │
        ▼
Backend API (FastAPI)
        │
        ├──> Database (PostgreSQL + PostGIS)
        │
        └──> Optimization Engine (OR-Tools)
                    │
                    └──> Distance API (OSRM)
```

รายละเอียดเพิ่มเติม: ดูที่ [`docs/SRS.md`](docs/SRS.md)

---

## 🛠️ Technology Stack

| ส่วน | เทคโนโลยีที่ใช้ |
|------|-----------------|
| Frontend | HTML5, CSS3, JavaScript (Vanilla) |
| Map | Leaflet.js + OpenStreetMap |
| Chart | Chart.js |
| Backend | FastAPI (Python 3.11+) |
| Database | PostgreSQL + PostGIS |
| Optimization | Google OR-Tools |
| Distance Calculation | OSRM (Open Source Routing Machine) |
| Containerization | Docker + Docker Compose |

---

## 📂 โครงสร้างโปรเจกต์

```
project-root/
├── frontend/              # หน้าเว็บ (หมิว)
│   ├── index.html
│   ├── css/
│   └── js/
│
├── backend/               # API และ Database (ขิง)
│   ├── api/
│   ├── services/          # Optimization Logic (อาร์ม)
│   └── models.py
│
├── database/
│   └── schema.sql
│
├── docs/
│   ├── SRS.md             # Software Requirements Specification
│   └── API_SPEC.md
│
├── docker-compose.yml
├── requirements.txt
└── README.md              # ไฟล์นี้
```

---

## 🚀 วิธีติดตั้งและรันโปรเจกต์

### สิ่งที่ต้องมีก่อน (Prerequisites)
- Python 3.11+
- Docker & Docker Compose
- Git

### ขั้นตอนการติดตั้ง

```bash
# 1. Clone โปรเจกต์
git clone https://github.com/[username]/route-optimization-engine.git
cd route-optimization-engine

# 2. สร้าง Virtual Environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. ติดตั้ง Dependencies
pip install -r requirements.txt

# 4. เริ่ม Database ด้วย Docker
docker-compose up -d database

# 5. รัน Migration (สร้างตาราง)
python backend/database.py --init

# 6. รัน Backend Server
uvicorn backend.app:app --reload --port 8000

# 7. เปิดเบราว์เซอร์
# ไปที่ http://localhost:8000 สำหรับหน้าเว็บ
# ไปที่ http://localhost:8000/docs สำหรับ API Documentation (Swagger)
```

---

## 📖 วิธีใช้งาน

1. **Upload ข้อมูลออเดอร์** → กด "Upload CSV" แล้วเลือกไฟล์ (ดูตัวอย่างที่ [`sample_data/orders.csv`](sample_data/orders.csv))
2. **ตรวจสอบข้อมูล** → ระบบแสดง Preview ให้ตรวจสอบก่อนยืนยัน
3. **กด "Optimize Routes"** → รอระบบคำนวณ (ประมาณ 5-30 วินาที)
4. **ดูผลลัพธ์บนแผนที่** → แต่ละเส้นทางจะแสดงด้วยสีต่างกัน
5. **Export ผลลัพธ์** → เลือก Export เป็น JSON หรือ CSV เพื่อส่งให้คนขับ

---

## 🧪 การทดสอบ

```bash
# รัน Unit Tests
pytest backend/tests/

# รัน Test เฉพาะ Optimization Engine
pytest backend/tests/test_optimizer.py -v
```

---

## 📊 ตัวอย่างผลลัพธ์ (Sample Results)

| Metric | ก่อนใช้ระบบ (Manual) | หลังใช้ระบบ (ROE) | ปรับปรุง |
|--------|----------------------|---------------------|----------|
| ระยะทางรวม | 450 กม./วัน | 280 กม./วัน | **-38%** |
| จำนวนรถที่ใช้ | 10 คัน | 7 คัน | **-30%** |
| อัตราส่งทันเวลา | 82% | 98% | **+16%** |

*(ตัวเลขนี้เป็นตัวอย่าง ควรแทนที่ด้วยผลทดสอบจริงจากโปรเจกต์)*

---

## 👥 ทีมพัฒนาและหน้าที่รับผิดชอบ

| ชื่อ | หน้าที่ | ส่วนที่รับผิดชอบ |
|------|---------|-------------------|
| **ขิง** | Backend & Database Engineer | Database Design, Order/Vehicle APIs, Authentication |
| **อาร์ม** | Optimization Engine Developer | OR-Tools Solver, Distance Matrix, KPI Calculation |
| **หมิว** | Frontend & Visualization Developer | UI/UX, Map Visualization, Dashboard |

---

## 📚 เอกสารเพิ่มเติม

- [Software Requirements Specification (SRS)](docs/SRS.md)
- [API Documentation](docs/API_SPEC.md)
- [Database Schema](database/schema.sql)

---

## ⚠️ ข้อจำกัดของระบบ (Known Limitations)

- รองรับออเดอร์สูงสุด ~100 ใบต่อครั้ง (เพื่อให้คำนวณเสร็จภายใน 30 วินาที)
- ไม่รองรับ Real-time GPS Tracking
- ไม่รองรับการเพิ่มออเดอร์ระหว่างที่รถกำลังวิ่ง (Dynamic Re-optimization)
- ใช้ข้อมูลถนนจาก OpenStreetMap ซึ่งอาจไม่ครบถ้วน 100% ในบางพื้นที่

---