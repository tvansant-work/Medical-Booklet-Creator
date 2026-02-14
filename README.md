# Medical Booklet Creator

Generates student profile PDFs for excursions and field activities — medical info, emergency contacts, learning support, swimming ability, dietary needs, and more.

*Created by Thomas van Sant.*

> 🔒 **Privacy:** All files are processed entirely on each user's own Mac. Nothing is transmitted over the internet. No data ever leaves the device.

---

## Setting up the GitHub repository (for Thomas)

### 1. Create a GitHub account
If you don't have one, go to [github.com](https://github.com) and sign up. A free account is all you need.

### 2. Create a new private repository
1. Click the **+** icon (top right) → **New repository**
2. Name it something like `medical-booklet-creator`
3. Set visibility to **Private** — important for a tool handling student data
4. Leave everything else unchecked — don't initialise with a README
5. Click **Create repository**

### 3. Install GitHub Desktop (easiest option)
Download from [desktop.github.com](https://desktop.github.com) — no Terminal needed for day-to-day use.

### 4. Add the files to your repository
1. Open GitHub Desktop → **File → Add Local Repository**
2. Choose the `field-kit-repo` folder (the one containing `app.py`)
3. If it asks to initialise a repository, click **Initialise**
4. You'll see all files listed as new. Write a summary like `Initial commit` and click **Commit to main**
5. Click **Publish repository** → make sure **Keep this code private** is ticked → **Publish**

Your repository is now live. The URL will be:
`https://github.com/YOUR_USERNAME/medical-booklet-creator`

### 5. Invite colleagues
1. On GitHub, go to your repository → **Settings → Collaborators**
2. Click **Add people** and enter each colleague's GitHub username or email
3. They'll receive an email invitation

Colleagues don't need GitHub Desktop — they just download a ZIP from the repo page.

---

## Pushing updates

When you update `app.py`, `config.yaml`, or `profiles.html`:

1. Replace the file in your local `field-kit-repo` folder
2. Open GitHub Desktop — it will show the changed files
3. Write a short summary (e.g. `Update medical card layout`) and click **Commit to main**
4. Click **Push origin**

Colleagues who cloned the repo (rather than downloading a ZIP) will receive updates **automatically** — `run.sh` checks GitHub and pulls any changes every time it launches. If they downloaded a ZIP, they'll need to re-download it for major updates.

---

## Repository structure

```
medical-booklet-creator/
├── app.py                ← Main application (never edit column logic here — use config.yaml)
├── config.yaml           ← Column name mappings — edit this if your data export changes
├── requirements.txt      ← Python package list — rarely needs changing
├── setup.sh              ← Staff run this once to install everything
├── run.sh                ← Staff run this each time to start the app
├── staff-setup.html      ← Setup guide staff open in their browser
├── .gitignore            ← Prevents any data files from being committed to GitHub
└── templates/
    └── profiles.html     ← PDF layout template
```

---

## Staff instructions

Direct staff to open `staff-setup.html` in their browser — it contains everything they need in a simple, step-by-step format with copyable commands.
