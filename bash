# Initialize the local directory as a Git repository
git init

# Add all files (bot.py, requirements.txt, etc.)
git add .

# Commit the files
git commit -m "Initial commit: Paybox VIP Bot"

# Rename the branch to main
git branch -M main

# Add your GitHub repository as the remote (Replace with your actual URL)
# Example: git remote add origin https://github.com/YourUsername/paymentbox.git
git remote add origin https://github.com/Noha345/paymentbox.git

# Push the code to GitHub
git push -u origin main
git add .
git commit -m "Update bot features"
git push origin main
git add requirements.txt
git commit -m "Add dependencies"
git push origin main
