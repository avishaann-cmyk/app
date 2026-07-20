# Frontend Dockerfile - React Application
# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Chromium is required for react-snap prerendering.
RUN apk add --no-cache chromium nss freetype harfbuzz ca-certificates ttf-freefont

# Copy package files
COPY package.json yarn.lock ./

# Install dependencies
RUN yarn install --frozen-lockfile

# Copy source code
COPY . .

# Build application
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ARG REACT_APP_BACKEND_URL=https://capeembercoffee.co.za
ENV REACT_APP_BACKEND_URL=${REACT_APP_BACKEND_URL}
RUN yarn build:prerender || yarn build

# Production stage
FROM node:20-alpine

WORKDIR /app

# Install serve to run the production build
RUN npm install -g serve

# Copy built application from builder
COPY --from=builder /app/build ./build

# Create non-root user for security
RUN addgroup -g 1000 appuser && \
    adduser -D -u 1000 -G appuser appuser && \
    chown -R appuser:appuser /app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:3000 || exit 1

# Expose port
EXPOSE 3000

# Serve the application
CMD ["serve", "-s", "build", "-l", "3000"]
