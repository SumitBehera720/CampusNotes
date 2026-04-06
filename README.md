<div align="center">

<img src="https://img.shields.io/badge/CampusNotes-4f46e5?style=for-the-badge&logo=readthedocs&logoColor=white" alt="CampusNotes" height="60"/>

# CampusNotes

### The Ultimate Premium Academic Note-Sharing Platform Built with Flask, PostgreSQL & Supabase

[![Live Demo](https://img.shields.io/badge/🚀%20Live%20Demo-Visit%20Site-4f46e5?style=for-the-badge)](http://campusnotes-prod-your-url.onrender.com)
[![GitHub Stars](https://img.shields.io/github/stars/SumitBehera720/CampusNotes?style=for-the-badge&color=4f46e5)](https://github.com/SumitBehera720/CampusNotes/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/SumitBehera720/CampusNotes?style=for-the-badge&color=4f46e5)](https://github.com/SumitBehera720/CampusNotes/network)
[![License: MIT](https://img.shields.io/badge/License-MIT-4f46e5?style=for-the-badge)](LICENSE)

<br/>

> 🎓 *A modern, fully-featured web application empowering university students to seamlessly share, discover, and collaborate on essential academic resources.*

<br/>

<!-- Insert absolute path/URL to your hero screenshot here -->
![CampusNotes Preview](Screenshot.png)

</div>

---

## 📌 Table of Contents

- [About the Project](#about)
- [Live Demo](#demo)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Key Pages & Views](#pages)
- [Getting Started](#getting-started)
- [Database & Storage Info](#database-info)
- [Roadmap](#roadmap)
- [Author](#author)

---

<a name="about"></a>
## 🎯 About the Project

**CampusNotes** is a robust, full-stack application designed specifically for college students. Moving beyond basic file-sharing, it incorporates social elements, gamification, and a deeply premium glassmorphic UI to make learning enjoyable and organized.

Built entirely with Python/Flask on the backend and pure HTML/CSS/JS on the frontend, this platform demonstrates the power of a finely-tuned monolithic architecture connected to modern cloud technologies like Supabase and Render.

---

<a name="demo"></a>
## 🌐 Live Demo

🔗 **[https://campusnotes-8crf.onrender.com/]**

> Optimal on both desktop and mobile platforms!

---

<a name="features"></a>
## ✨ Features

<table>
  <tr>
    <td>📚</td>
    <td><strong>Advanced Search & Filtering</strong></td>
    <td>Instantly locate notes by Subject, Branch, Semester, Difficulty, and File Type.</td>
  </tr>
  <tr>
    <td>📊</td>
    <td><strong>Student Dashboard</strong></td>
    <td>A personalized hub tracking your uploads, saves, and total downloads.</td>
  </tr>
  <tr>
    <td>🏅</td>
    <td><strong>Gamification & Badges</strong></td>
    <td>Earn badges (e.g., 'First Note', 'Top Rated') based on your contributions.</td>
  </tr>
  <tr>
    <td>☁️</td>
    <td><strong>Cloud Storage</strong></td>
    <td>Secure, scalable file persistence handled entirely by Supabase buckets.</td>
  </tr>
  <tr>
    <td>🔔</td>
    <td><strong>Real-time Notifications</strong></td>
    <td>Get instantly alerted about new followings, badges, and downloads.</td>
  </tr>
  <tr>
    <td>👑</td>
    <td><strong>Admin Control Panel</strong></td>
    <td>Dedicated UI for admins to moderate uploads, handle reports, and manage users.</td>
  </tr>
  <tr>
    <td>📱</td>
    <td><strong>Fully Responsive UX</strong></td>
    <td>A fluid, glassmorphic UI that looks stunning on every device.</td>
  </tr>
</table>

---

<a name="tech-stack"></a>
## 🛠️ Tech Stack

<div align="center">

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=Render&logoColor=white)

</div>

| Component | Technology | Description |
|-----------|------------|-------------|
| **Backend** | Python & Flask | Core routing, rendering, business logic |
| **Frontend** | HTML5 / CSS3 / JS | Vanilla, dependency-free UI w/ Jinja2 |
| **Database** | PostgreSQL | Handled via Supabase (psycopg pooling) |
| **Storage** | Supabase Buckets | Secure PDF/PPT cloud blob storage |
| **Deployment**| Render.com | Gunicorn w/ worker threading |

---

<a name="pages"></a>
## 📸 Key Pages & Views

*(You can replace the placeholder URLs with actual local screenshot paths like `./screenshots/home.png` once you take them)*

| ![Home Page](https://via.placeholder.com/600x338?text=Home+Page+Preview) | ![Note View](https://via.placeholder.com/600x338?text=Note+Detail+Preview) |
| :---: | :---: |
| *Modern Landing Page & Quick Stats* | *Clear, concise Note Reader & Download section* |

| ![Dashboard](https://via.placeholder.com/600x338?text=Dashboard+Preview) | ![Admin Panel](https://via.placeholder.com/600x338?text=Admin+Panel+Preview) |
| :---: | :---: |
| *Personalized Metric Dashboard* | *Administrator Command Center* |

---

<a name="getting-started"></a>
## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/SumitBehera720/CampusNotes.git
cd CampusNotes
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the root directory to store your sensitive cloud configuration:

```env
SECRET_KEY=your-flask-secret-key
DATABASE_URL=postgresql://your-db-details
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-secure-service-role-key
```
*(Note: If no database URL is provided, the app intelligently falls back to a local SQLite database file)*

### 4. Run the Application

```bash
python app.py
```
Then navigate to `http://127.0.0.1:5000` in your browser.

---

<a name="database-info"></a>
## 🗄️ Database & Storage Info

CampusNotes is optimized for Free-Tier deployments with a very healthy student cap:

*   **Total Data Capacity:** ~1 GB (Via Supabase Buckets)
*   **Database Capacity:** 500 MB PostgreSQL (Supports 1000s of users & metadata)
*   **Optimal Concurrency:** Tuned via Gunicorn pools on Free-Tier Render to process dozens of simultaneous hits.
*   **Max Note Upload Size:** Hard-capped at 25MB for safety.

---

<a name="roadmap"></a>
## 🗺️ Roadmap

- [x] Integrate robust PostgreSQL connection pooling
- [x] Migrate file storage from ephemeral disk to Supabase Cloud
- [x] Create comprehensive Admin/Moderator dashboard
- [x] Implement User Dashboards, Gamification, and Notifications
- [ ] Implement robust Note Verification pipelines
- [ ] Add Email notifications & Password Resets
- [ ] Dedicated Dark Mode Toggle

---

<a name="author"></a>
## 👨‍💻 Author

<div align="center">

**Sumit Behera**

*Full-Stack Developer | Software Engineer*

[![GitHub](https://img.shields.io/badge/GitHub-SumitBehera720-181717?style=for-the-badge&logo=github)](https://github.com/SumitBehera720)

<br/>

⭐ **If you found this project helpful or inspiring, please consider giving it a star!** ⭐

</div>

---

<div align="center">

© 2026 CampusNotes · Designed & Developed with ❤️ by **Sumit Behera**

</div>
