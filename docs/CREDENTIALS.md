# Getting your credentials

> ⚠️ These are your live Zerodha login credentials. Treat them like a password — store them
> only in `.env` (git-ignored) or your hosting platform's secret manager. Never paste them into
> chat with an AI agent; the server's own login page is designed so you never have to.

You need three values from your Zerodha account.

---

## `ZERODHA_USER_ID`

This is your **Zerodha Client ID** — a 6-character alphanumeric code printed on all Zerodha
communications (e.g. `ZK1234`, `AB5678`).

**Where to find it:**

1. Open [kite.zerodha.com](https://kite.zerodha.com) in your browser and log in.
2. Click your **name / avatar** in the top-right corner.
3. Select **My Profile**.
4. Your Client ID appears at the top of the profile page under your name.

Alternatively, check any email from Zerodha — it appears in the subject line and footer of every
account-related email as *"Client ID: ZK1234"*.

```env
ZERODHA_USER_ID=ZK1234
```

---

## `ZERODHA_PASSWORD`

This is the **password you use to log in to Kite** (the Zerodha trading platform).

It is the same password you type on the [kite.zerodha.com](https://kite.zerodha.com) login page —
**not** your Zerodha account PIN, not your UPI PIN, not your bank password.

> **Tip:** If you have forgotten it, reset it at
> `Console → My Account → Password & Security → Reset Login Password`
> ([console.zerodha.com](https://console.zerodha.com))

```env
ZERODHA_PASSWORD=your_kite_login_password
```

---

## `ZERODHA_TOTP_SECRET`

This is the **base32 secret key** behind your Zerodha TOTP authenticator — the raw key that
Google Authenticator / Authy encodes as a QR code. Providing this lets the server generate the
6-digit code automatically, useful for unattended/remote deployments.

> If `ZERODHA_TOTP_SECRET` is not set, you will be prompted for the 6-digit code on the
> `/login` browser page each time you log in.

Zerodha shows you this secret **only once** — when you first set up TOTP. If you have already
set up TOTP and did not save the secret, you must reset 2FA to get a new one.

**Option A — Setting up TOTP for the first time**

1. Go to [console.zerodha.com](https://console.zerodha.com) and log in.
2. Navigate to **My Account → Password & Security**.
3. Under the **Two-factor authentication** section, click **Set up TOTP**.
4. Zerodha displays a **QR code** and, below it, a text string that says something like:
   ```
   Can't scan? Enter this key manually: JBSWY3DPEHPK3PXP
   ```
   That `JBSWY3DPEHPK3PXP` is your **TOTP secret**. Copy it exactly.
5. Scan the QR code with Google Authenticator / Authy to register it.
6. Enter the 6-digit code from your authenticator app to confirm setup.
7. Paste the secret into your `.env`:
   ```env
   ZERODHA_TOTP_SECRET=JBSWY3DPEHPK3PXP
   ```

**Option B — You already have TOTP set up but never saved the secret**

1. Go to [console.zerodha.com](https://console.zerodha.com) → **My Account → Password & Security**.
2. Under **Two-factor authentication**, click **Reset TOTP**.
3. Zerodha will send a verification to your registered email/mobile.
4. After verifying, a new QR code and secret are shown — follow steps 4–7 from Option A above.

```env
ZERODHA_TOTP_SECRET=YOUR_BASE32_SECRET_HERE
```
