#!/bin/bash
# Ready Concierge — Push to GitHub & trigger Railway deploy
# Run this from the ready-concierge directory:
#   cd ~/Desktop/ready-concierge && bash deploy.sh

set -e

echo "=== Ready Concierge Deploy ==="

# Initialize git if needed
if [ ! -d .git ]; then
  echo "Initializing git repo..."
  git init
  git remote add origin https://github.com/readyconcierge/ready-concierge.git
else
  echo "Git repo already initialized."
fi

# Make sure remote is set
if ! git remote get-url origin &>/dev/null; then
  git remote add origin https://github.com/readyconcierge/ready-concierge.git
fi

# Fetch the current remote state
echo "Fetching remote..."
git fetch origin main --depth=1 2>/dev/null || true

# Stage all files (respects .gitignore)
echo "Staging files..."
git add -A

# Commit
echo "Committing..."
git commit -m "feat: add guest memory, task tracker, knowledge base, GM digest, feedback loop, reply-time tracking, SendGrid migration, multi-tenant architecture, staff training PDF

Major updates:
- Migrated from Mailgun to SendGrid (inbound parse + outbound)
- Multi-tenant Company → Property → Stream architecture
- Guest memory system (recognizes returning guests)
- Task extraction and tracking from draft replies
- Knowledge base with auto-seeding from starter files
- Weekly GM intelligence digest with AI insights
- One-click feedback tokens on every draft
- Reply-time tracking (processing_ms)
- Staff training PDF one-pager
- Updated README with full deployment guide
- Next.js dashboard scaffolding

Co-Authored-By: Claude <noreply@anthropic.com>"

# Force push to main (overwrites old Mailgun-based code)
echo "Pushing to GitHub..."
git branch -M main
git push -u origin main --force

echo ""
echo "=== Done! Railway will auto-deploy from GitHub. ==="
echo "Check deployment at: https://railway.com/project/9f50752d-76e8-4e47-9867-5c8e3c44aaa0"
