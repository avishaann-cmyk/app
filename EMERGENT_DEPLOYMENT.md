# Emergent Deployment Guide

## Git Configuration for Emergent

Your repository is now ready to be pushed to Emergent. Follow these steps:

### 1. Add Emergent Remote

Replace `YOUR_EMERGENT_PROJECT_URL` with your actual Emergent Git repository URL:

```bash
git remote add origin YOUR_EMERGENT_PROJECT_URL

# Examples:
# git remote add origin https://git.emergentagent.com/username/capeembercoffee.git
# git remote add origin git@emergent.git:capeembercoffee.git
```

### 2. Set Up Git Credentials (if using HTTPS)

Store credentials for automatic authentication:

```bash
# For GitHub or Emergent via HTTPS
git config --global credential.helper store

# Or use OAuth token
git config --global user.name "Your Name"
git config --global user.email "your.email@emergent.com"
```

### 3. Push to Emergent

```bash
# Push current branch
git push -u origin main

# Or push all branches
git push -u origin --all
```

### 4. Verify Push

```bash
# Check remote configuration
git remote -v

# View recent commits on remote
git log --oneline -5
```

---

## Current Repository Status

**Latest Commit**: `2a21c5e`

```
Complete: Deployment infrastructure + feature updates

✓ 36 files changed
✓ Features complete
✓ Infrastructure ready
✓ Documentation complete
```

### Files Included

**Code Updates** (18 modified):
- backend/server.py
- 8 frontend pages
- 3 frontend components
- app.js, index.css, .gitignore

**Deployment Infrastructure** (10 new):
- Dockerfiles (2)
- docker-compose files (2)
- nginx.conf
- deploy.sh
- GitHub Actions workflow
- Scripts (health-check, backup)
- .env.production.example

**Documentation** (4 guides):
- DEPLOYMENT_SUMMARY.md
- DEPLOYMENT.md
- DEPLOYMENT_CHECKLIST.md
- GITHUB_ACTIONS_SETUP.md

---

## Quick Push Command

```bash
cd /app

# If you haven't added remote yet:
git remote add origin YOUR_EMERGENT_GIT_URL

# Push to Emergent:
git push -u origin main
```

Replace `YOUR_EMERGENT_GIT_URL` with your actual repository URL.

---

## After Pushing to Emergent

1. **In Emergent Dashboard**:
   - Verify commits appear in project
   - Check that all files are included
   - Review deployment configuration

2. **Setup Secrets in Emergent** (if using CI/CD):
   - `MONGO_PASSWORD`
   - `PAYFAST_MERCHANT_ID` / `PAYFAST_MERCHANT_KEY`
   - `RESEND_API_KEY`
   - `JWT_SECRET`

3. **Configure Webhooks** (if deploying from Emergent):
   - Connect to your production server
   - Setup automatic deployments on push

4. **Deployment**:
   - Follow DEPLOYMENT_CHECKLIST.md
   - Run: `./deploy.sh deploy --env production`

---

## Troubleshooting

### Authentication Issues

```bash
# Test SSH connection
ssh -T git@emergent.git

# Test HTTPS connection
git credential approve <<EOF
protocol=https
host=git.emergentagent.com
username=your_username
password=your_token
EOF
```

### Push Rejected

```bash
# Force push (use with caution!)
git push -u origin main --force

# Or pull and merge first
git pull origin main
git push -u origin main
```

### Remove Wrong Remote

```bash
git remote remove origin
git remote add origin CORRECT_URL
git push -u origin main
```

---

## Support

- **Emergent Docs**: Check Emergent dashboard for Git URL
- **Git Help**: `git --help`
- **SSH Setup**: `ssh-keygen -t rsa -b 4096 -f ~/.ssh/emergent`

---

**Status**: ✅ Ready to Push
**Files Staged**: 36
**Latest Commit**: Complete deployment infrastructure + feature updates
