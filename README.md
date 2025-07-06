# Fantasy Baseball Helper ⚾

Your complete fantasy baseball analytics platform built with modern web technologies.

## 🎯 Features

### 🔍 MLB Player Analytics
- **Real-time player search** with MLB Stats API integration
- **Comprehensive statistics** including advanced metrics (OPS, BABIP, etc.)
- **Multi-season data** with historical performance tracking
- **Live data caching** for optimal performance

### 🏆 Fantasy League Integration
- **ESPN Fantasy Baseball** - Connect your leagues with cookie authentication
- **Yahoo Fantasy Sports** - OAuth-ready integration framework
- **Team roster management** with position tracking
- **League standings** and team performance metrics

### 📊 Data & Analytics
- **SQLite database** with Prisma ORM for fast local storage
- **Player statistics** with seasonal breakdowns
- **Team roster tracking** with acquisition history
- **League synchronization** for real-time updates

## 🛠 Tech Stack

- **Frontend**: Next.js 15, TypeScript, Tailwind CSS
- **Backend**: Next.js API Routes, Prisma ORM
- **Database**: SQLite (development), PostgreSQL-ready
- **State Management**: Zustand, TanStack Query
- **APIs**: MLB Stats API, ESPN Fantasy API, Yahoo Fantasy API

## 🚀 Getting Started

### Prerequisites
- Node.js 18+ 
- npm or yarn

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/fantasy-baseball-helper.git
   cd fantasy-baseball-helper
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Set up the database**
   ```bash
   npx prisma generate
   npx prisma migrate dev
   ```

4. **Start the development server**
   ```bash
   npm run dev
   ```

5. **Open in browser**
   ```
   http://localhost:3000
   ```

## 📖 Usage

### Player Search & Analytics
1. Navigate to the "Player Search & Stats" tab
2. Search for any active MLB player (e.g., "Mike Trout", "Aaron Judge")
3. View comprehensive statistics and advanced metrics
4. Switch between different seasons to see historical performance

### League Integration

#### ESPN Fantasy Baseball
1. Go to "League Integration" tab
2. Select "ESPN Fantasy"
3. Follow the instructions to get your SWID and ESPN_S2 cookies:
   - Open your ESPN fantasy league in a browser
   - Open Developer Tools (F12) → Application → Cookies
   - Find cookies named "swid" and "espn_s2"
   - Copy their values and your League ID from the URL
4. Connect and view your league data!

#### Yahoo Fantasy Baseball
1. Select "Yahoo Fantasy" 
2. OAuth integration framework is ready
3. Requires Yahoo Developer Console setup for full functionality

## 🏗 Project Structure

```
├── src/
│   ├── app/                 # Next.js App Router
│   │   ├── api/            # API endpoints
│   │   │   ├── players/    # MLB player data endpoints
│   │   │   └── leagues/    # Fantasy league endpoints
│   │   ├── globals.css     # Global styles
│   │   ├── layout.tsx      # Root layout
│   │   └── page.tsx        # Home page
│   ├── components/         # React components
│   │   ├── LeagueConnection.tsx
│   │   ├── LeagueRoster.tsx
│   │   ├── PlayerSearch.tsx
│   │   └── PlayerStats.tsx
│   └── lib/               # Utility libraries
│       ├── espn-api.ts    # ESPN API integration
│       ├── mlb-api.ts     # MLB Stats API
│       ├── prisma.ts      # Database client
│       └── yahoo-api.ts   # Yahoo API integration
├── prisma/                # Database schema & migrations
└── public/               # Static assets
```

## 🔧 API Endpoints

### MLB Player Data
- `GET /api/players/search?name={name}` - Search for players
- `GET /api/players/{id}/stats?season={year}` - Get player statistics

### Fantasy League Data  
- `POST /api/leagues/espn/connect` - Connect ESPN league
- `POST /api/leagues/yahoo/connect` - Connect Yahoo leagues
- `GET /api/leagues/{id}/teams` - Get league teams
- `GET /api/leagues/{id}/teams/{teamId}/roster` - Get team roster

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **MLB Stats API** for providing comprehensive baseball statistics
- **ESPN** and **Yahoo** for fantasy sports data access
- **Next.js**, **Prisma**, and **Tailwind CSS** for the amazing developer experience

---

Built with ❤️ for fantasy baseball enthusiasts everywhere!