# Replit Deployment Instructions

## Setting up your Replit Project

### Method 1: Import from GitHub
1. Go to [replit.com](https://replit.com)
2. Click "Import from GitHub"
3. Enter your repository URL: `https://github.com/chickenbutt322/HP.git`
4. Click "Import"

### Method 2: Manual Setup
1. Create a new Repl
2. Select "Python" as the language
3. In the shell, run:
```bash
git clone https://github.com/chickenbutt322/HP.git .
```

## Build and Run Commands

### Build Command (set in Replit config):
```bash
pip install -r requirements.txt
```

### Run Command (set in Replit config):
```bash
python DeepInfamousDirectories/main.py
```

## Environment Variables

Add these environment variables in the "Secrets" tab:
- `TOKEN` - Your Discord bot token
- `MONGODB_URI` - Your MongoDB connection string

## Updating Replit from GitHub

After pushing changes to GitHub, update Replit by running in the shell:
```bash
git pull origin main
pip install -r requirements.txt
```

## Alternative: Refresh Replit Workspace

If you encounter issues, completely refresh your workspace:
```bash
cd ~
rm -rf workspace/
git clone https://github.com/chickenbutt322/HP.git workspace
cd workspace
pip install -r requirements.txt
```

## Troubleshooting

1. **If pip is not found**: Make sure you're using the Python Repl template
2. **If Poetry is not found**: Use the requirements.txt approach instead
3. **Indentation errors**: The code has been fixed to prevent these
4. **Security scan output**: This is just a scan result, not your actual code