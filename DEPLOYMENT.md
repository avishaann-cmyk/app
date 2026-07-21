# Deployment Guide - Cape Ember Coffee Co.

## Overview

This application is deployed using Docker containers orchestrated with Docker Compose. The architecture includes:

- **Backend**: FastAPI application running on port 8000
- **Frontend**: React application running on port 3000
- **Database**: MongoDB for data storage
- **Reverse Proxy**: Nginx for routing and SSL termination
- **Load Balancing**: Request rate limiting and caching

## Prerequisites

Before deployment, ensure you have:

- Docker Engine 20.10+
- Docker Compose 2.0+
- Git
- SSH access to production server (if deploying remotely)

## Quick Start

### Local Development

1. **Clone the repository**:
   ```bash
   git clone https://github.com/capeembercoffee/capeembercoffee.co.za.git
   cd capeembercoffee.co.za
   ```

2. **Start services locally**:
   ```bash
   docker-compose up -d
   ```

3. **Access the application**:
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

4. **Stop services**:
   ```bash
   docker-compose down
   ```

### Staging Deployment

1. **Prepare environment**:
   ```bash
   cp .env.example .env
   # Edit .env with staging values
   vim .env
   ```

2. **Build and deploy**:
   ```bash
   chmod +x deploy.sh
   ./deploy.sh build --env staging
   ./deploy.sh deploy --env staging
   ```

3. **Verify deployment**:
   ```bash
   ./deploy.sh health --env staging
   ```

### Production Deployment

#### 1. Server Setup

```bash
# SSH into production server
ssh deploy@capeembercoffee.co.za

# Create deployment directory
sudo mkdir -p /opt/cape-ember-coffee
sudo chown deploy:deploy /opt/cape-ember-coffee

# Clone repository
cd /opt/cape-ember-coffee
git clone https://github.com/capeembercoffee/capeembercoffee.co.za.git
cd capeembercoffee.co.za
```

#### 2. Configure Production Environment

```bash
# Create production environment file
cp .env.production.example .env.production

# Edit with production values
vim .env.production

# Important values to set:
# - MONGO_PASSWORD: Strong password for MongoDB
# - MONGO_USER: MongoDB username
# - JWT_SECRET: Generate with: openssl rand -base64 32
# - PAYFAST_MERCHANT_ID & PAYFAST_MERCHANT_KEY: From PayFast merchant account
# - RESEND_API_KEY: Email service API key
```

#### 3. SSL Certificate Setup

```bash
# Create SSL directory
mkdir -p ssl/certs

# Option A: Use Let's Encrypt with Certbot
sudo certbot certonly --standalone \
  -d capeembercoffee.co.za \
  -d www.capeembercoffee.co.za

# Copy certificates
sudo cp /etc/letsencrypt/live/capeembercoffee.co.za/fullchain.pem ssl/certs/cert.pem
sudo cp /etc/letsencrypt/live/capeembercoffee.co.za/privkey.pem ssl/certs/key.pem
sudo chown deploy:deploy ssl/certs/*

# Option B: Use existing certificates (copy to ssl/certs/)
cp /path/to/cert.pem ssl/certs/
cp /path/to/key.pem ssl/certs/
```

#### 4. Build Docker Images

```bash
# Build images for production
docker build -t cape-ember/backend:latest ./backend
docker build -t cape-ember/frontend:latest ./frontend
```

#### 5. Deploy Application

```bash
# Make deploy script executable
chmod +x deploy.sh

# Deploy (this runs tests first)
./deploy.sh deploy --env production

# Or skip tests if needed
./deploy.sh deploy --env production --no-tests
```

#### 6. Verify Deployment

```bash
# Check container status
docker-compose -f docker-compose.prod.yml ps

# View logs
docker-compose -f docker-compose.prod.yml logs -f

# Health check
curl https://capeembercoffee.co.za/health
curl https://capeembercoffee.co.za/api/health
```

## Deployment Workflow

### Using the Deploy Script

```bash
# 1. Check prerequisites
./deploy.sh check

# 2. Build images
./deploy.sh build --env production

# 3. Run tests
./deploy.sh test

# 4. Deploy
./deploy.sh deploy --env production

# 5. Monitor logs
./deploy.sh logs --env production

# 6. Health check
./deploy.sh health --env production
```

### Manual Docker Compose

```bash
# Build images
docker-compose -f docker-compose.prod.yml build

# Start services
docker-compose -f docker-compose.prod.yml up -d

# Scale services (if needed)
docker-compose -f docker-compose.prod.yml up -d --scale backend=2

# Stop services
docker-compose -f docker-compose.prod.yml down

# View logs
docker-compose -f docker-compose.prod.yml logs -f backend
```

## Management

### View Logs

```bash
# All services
docker-compose -f docker-compose.prod.yml logs

# Specific service
docker-compose -f docker-compose.prod.yml logs backend
docker-compose -f docker-compose.prod.yml logs frontend
docker-compose -f docker-compose.prod.yml logs nginx

# Follow logs in real-time
docker-compose -f docker-compose.prod.yml logs -f
```

### Backup Database

```bash
# Backup MongoDB
docker exec cape-ember-mongodb-prod mongodump \
  --authenticationDatabase admin \
  -u $MONGO_USER -p $MONGO_PASSWORD \
  --out /backup/$(date +%Y%m%d_%H%M%S)

# Restore from backup
docker exec cape-ember-mongodb-prod mongorestore \
  --authenticationDatabase admin \
  -u $MONGO_USER -p $MONGO_PASSWORD \
  /backup/backup-folder
```

### Update Application

```bash
# Pull latest code
git pull origin main

# Rebuild images
docker-compose -f docker-compose.prod.yml build

# Restart services with new images
docker-compose -f docker-compose.prod.yml up -d
```

### Scale Services

```bash
# Scale backend to 2 instances
docker-compose -f docker-compose.prod.yml up -d --scale backend=2

# Scale frontend to 2 instances
docker-compose -f docker-compose.prod.yml up -d --scale frontend=2
```

## Troubleshooting

### Services Won't Start

```bash
# Check logs for errors
docker-compose -f docker-compose.prod.yml logs

# Verify environment variables
docker exec cape-ember-backend-prod env | grep -E '^(MONGO|PAYFAST)'

# Recreate containers
docker-compose -f docker-compose.prod.yml down -v
docker-compose -f docker-compose.prod.yml up -d
```

### SSL Certificate Issues

```bash
# Verify certificate
openssl x509 -in ssl/certs/cert.pem -text -noout

# Renew with Let's Encrypt
sudo certbot renew

# Update container
docker-compose -f docker-compose.prod.yml restart nginx
```

### Database Connection Issues

```bash
# Test MongoDB connection
docker exec cape-ember-mongodb-prod mongosh \
  -u $MONGO_USER -p $MONGO_PASSWORD --eval "db.runCommand('ping')"

# Check database size
docker exec cape-ember-mongodb-prod du -sh /data/db
```

### API Performance Issues

```bash
# Check backend logs
docker-compose -f docker-compose.prod.yml logs backend

# View Nginx access logs
docker exec cape-ember-nginx-prod tail -f /var/log/nginx/access.log

# Monitor resource usage
docker stats
```

## Rollback Procedure

If deployment fails, you can rollback:

```bash
# 1. Check git history
git log --oneline -10

# 2. Checkout previous version
git checkout <previous-commit-hash>

# 3. Rebuild and restart
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml build --no-cache
docker-compose -f docker-compose.prod.yml up -d

# 4. Verify services
docker-compose -f docker-compose.prod.yml ps
```

## Monitoring & Alerts

### Setup Monitoring

```bash
# Example: Check service health every 5 minutes
*/5 * * * * /opt/cape-ember-coffee/check-health.sh >> /var/log/cape-ember-health.log 2>&1
```

### Uptime Monitoring

Configure external monitoring services:
- UptimeRobot: Monitor endpoint availability
- DataDog or New Relic: Application performance monitoring
- PagerDuty: Alert escalation

## Security

### Best Practices

1. **Never commit secrets** to git:
   - Keep `.env.production` out of version control
   - Use `.gitignore` for sensitive files

2. **SSL/TLS**:
   - Use Let's Encrypt for free certificates
   - Auto-renew certificates with certbot

3. **Database Security**:
   - Use strong MongoDB passwords
   - Bind MongoDB to internal network only
   - Regular backups

4. **API Security**:
   - Rate limiting enabled in nginx
   - CORS properly configured
   - JWT secret properly secured

## Support

For deployment issues:

1. Check logs: `docker-compose -f docker-compose.prod.yml logs`
2. Verify environment: `docker exec <container> env | sort`
3. Test connectivity: `curl -v https://capeembercoffee.co.za/health`
4. Contact: deployment@capeembercoffee.co.za

---

**Last Updated**: 2026-07-07
**Version**: 1.0.0
