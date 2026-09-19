<h1 align="center">BillShare</h1>

<p align="center">
  A Django app for splitting a shared bill fairly.<br>
  A host creates a room and shares a 6-character code. Others join, the host approves them, and everyone logs what they ordered.<br>
  The app splits items evenly or by weight, allocates tax and tip proportionally, and tracks payments until everyone's settled.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Django-6.x-092E20?style=flat-square&logo=django&logoColor=white" alt="Django 6.x">
  <img src="https://img.shields.io/badge/Tailwind-CDN-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white" alt="Tailwind CDN">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="MIT License">
</p>

<p align="center">
  <a href="#demo">Demo</a> ·
  <a href="#features">Features</a> ·
  <a href="#tech-stack">Tech Stack</a> ·
  <a href="#getting-started">Getting Started</a> ·
  <a href="#contact">Contact</a>
</p>

## Demo

<p align="center">
  <img src="demo.gif" alt="BillShare demo" width="800">
</p>

<p align="center">
  <em>Creating a room, sharing the join code, approving a member, and splitting a shared item.</em>
</p>

## Features

<table>
  <tr>
    <td width="50%" valign="top">

**Rooms and membership**

- Host creates a room and gets a 6-character join code
- Join by typing the code or opening a link
- Approval-gated: pending members see nothing until the host approves them
- Statuses: pending, approved, rejected, removed

</td>
    <td width="50%" valign="top">

**Splitting and payments**

- Split an item evenly, or give each person a weight (weight 2 pays double)
- Tax and tip allocated in proportion to each member's subtotal
- Host records full or partial payments
- Running balance on every member's row

</td>
  </tr>
  <tr>
    <td width="50%" valign="top">

**Guests without accounts**

- Add someone who isn't going to sign up
- They participate in splits like any other member
- If they sign up later, a one-time claim link transfers their items, shares, and payments to their real account

</td>
    <td width="50%" valign="top">

**Views and cleanup**

- Personal debts page — what you owe, to whom, across all rooms
- Member breakdown page with that member's items and payments
- Archive a settled room; delete is a two-step flow, blocked if anyone still owes
- Custom login and signup, password show/hide toggle

</td>
  </tr>
</table>

## Tech Stack

| | |
|---|---|
| **Backend** | ![Django](https://img.shields.io/badge/-Django%206.x-092E20?style=flat-square&logo=django&logoColor=white) ![SQLite](https://img.shields.io/badge/-SQLite%20(dev)-003B57?style=flat-square&logo=sqlite&logoColor=white) ![python-dotenv](https://img.shields.io/badge/-python--dotenv-3776AB?style=flat-square&logo=python&logoColor=white) |
| **Frontend** | ![Django Templates](https://img.shields.io/badge/-Django%20Templates-092E20?style=flat-square) ![Tailwind CSS](https://img.shields.io/badge/-Tailwind%20CDN-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white) ![JavaScript](https://img.shields.io/badge/-Vanilla%20JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black) |
| **Tools** | ![Git](https://img.shields.io/badge/-Git-F05032?style=flat-square&logo=git&logoColor=white) ![pip](https://img.shields.io/badge/-pip-3775A9?style=flat-square) ![Django Admin](https://img.shields.io/badge/-Django%20Admin-092E20?style=flat-square) |

## Getting Started

**Prerequisites:** Python 3.10+, pip, and Git.

<details>
<summary><b>Setup instructions</b></summary>

<br>

**1. Clone the repository**

```bash
git clone https://github.com/SalmonFlight/BillShare.git
cd BillShare
```

**2. Create and activate a virtual environment**

```bash
python -m venv .venv
source .venv/bin/activate      # Mac/Linux
.venv\Scripts\activate         # Windows
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Set up environment variables**

```bash
cp .env.example .env
```

Then edit `.env`:

```
SECRET_KEY=your-secret-key-here
DEBUG=True
```

To generate a `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

**5. Set up the database, create an admin account, and run the server**

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

**6. Open the app**

Go to http://127.0.0.1:8000/ and log in. Then create a room and share the join code.

</details>

## What I Learned

| Area | Details |
|---|---|
| **Per-object permissions** | Access can't be decided until the room and the user's membership are loaded. One helper does the check; every room view calls it. |
| **403 vs 404** | 403 when the user knows the room exists but lacks rights (a pending member). 404 when they shouldn't be able to confirm it exists (a non-host on a host-only page). Enforced by queryset filtering. |
| **Decimal money** | Every amount is a `DecimalField`. Floats can't represent `0.10` exactly, and the error compounds across items, tax, tip, and payments. |
| **Exact allocation** | Item cost splits by weight; tax and tip split by subtotal. `ROUND_HALF_EVEN` (banker's rounding), and the last member absorbs the remainder so shares sum to the total. |
| **Avoiding N+1** | The dashboard loads members, shares, and payments in a fixed number of queries. A naive `annotate(Sum(...), Sum(...))` produces a cartesian JOIN and doubles the totals. |
| **Function-based views** | Every room view has a per-object permission check. FBVs read top-to-bottom: fetch, check, render. CBVs would split that across `get_object` and `get_queryset`. |
| **Transactions** | The guest claim flow moves FKs across multiple tables. It's wrapped in `transaction.atomic()` so a mid-way failure can't leave things half-moved. |

### Biggest Challenge

> **The problem:** The guest claim flow. A guest is a real `User` row with an unusable password, so their items, shares, and payments all point at that shadow user. When the guest signs up and claims their entry, every one of those foreign keys has to move to the real account — without losing anything, and without breaking if the real user already has a share on the same item.
>
> **The solution:** One transaction. Reassign each `ItemShare` (merging weights if the real user already had a share on that item), update all `Payment` rows and `Item.created_by` in bulk, copy the display name across, then delete the shadow. Nothing commits until it all succeeds.

### Takeaway

> **When a relationship has data, it needs its own table.** I could have used a `ManyToManyField` between users and rooms, but the relationship carries a status, a guest flag, and a claim code. Django's through-model pattern exists for exactly this — and once it clicked, the whole permission model became simpler.

## Future Improvements

- [ ] Peer-to-peer settlement (currently single-creditor — everyone owes the host)
- [ ] Test suite for the permission matrix and rounding
- [ ] Email notifications when items are added or payments are recorded
- [ ] Receipt photo upload
- [ ] Postgres for production and deployment

Contributions are welcome. Feel free to open an issue or submit a pull request.

## Contact

I'm actively looking for SWE roles.

<p>
  <a href="https://github.com/SalmonFlight"><img src="https://img.shields.io/badge/GitHub-SalmonFlight-181717?style=flat-square&logo=github&logoColor=white" alt="GitHub"></a>
  <a href="https://www.linkedin.com/in/brayden-aaron-santoso-351010434/"><img src="https://img.shields.io/badge/LinkedIn-Connect-0A66C2?style=flat-square" alt="LinkedIn"></a>
  <a href="mailto:B.AaronSantoso@gmail.com"><img src="https://img.shields.io/badge/Email-B.AaronSantoso%40gmail.com-D14836?style=flat-square&logo=gmail&logoColor=white" alt="Email: B.AaronSantoso@gmail.com"></a>
</p>

---

## Acknowledgments

- Django Documentation
- Tailwind CSS

## License

This project is open source under the MIT License.
