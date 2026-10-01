FROM node:20-alpine

WORKDIR /app

# The lockfile is copied and installed with `npm ci` rather than `npm install`
# from package.json alone. Without it two builds of the same commit can resolve
# different patch versions, which is the kind of difference that shows up as
# "works on my machine" much later.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host so the dev server is reachable from outside the container. Vite's
# default binds to localhost inside the container, which publishes a port that
# answers nothing.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]