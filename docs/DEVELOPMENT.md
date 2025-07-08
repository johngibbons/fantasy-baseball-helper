# Development Guide

## Quick Start for Development

### 🚀 Setting Up Persistent Development Data

To avoid having to re-import your league data every time you refresh the page during development:

1. **Import your real ESPN league** (one-time setup):
   - Start the dev server: `npm run dev`
   - Go to League Integration tab
   - Connect your ESPN league with your credentials
   - **Your real league data is now saved locally and will persist!**

2. **Your data will now persist!** Your imported league includes:
   - Your actual ESPN league name and settings
   - All real teams with actual names and stats
   - Real manager names (no more cryptic IDs)
   - Actual roster data with real players

### 📊 Available Development Commands

```bash
# Reset database (if you want to start fresh and re-import your league)
npm run db:reset

# Standard development server
npm run dev

# Run all tests (recommended before committing)
npm test

# Test with coverage
npm run test:coverage

# Test-driven development (watch mode)
npm run test:watch
```

### 🔄 Development Workflow

1. **Start development server**: `npm run dev`
2. **Access your persistent league**: Go to League Integration tab → Your imported ESPN league should already be there
3. **Make changes to code**
4. **Refresh page** → Your real data persists! No need to re-import
5. **Write tests first** when adding new features (TDD approach)
6. **Run tests** before committing: `npm test`

### 🎯 TDD Workflow (Recommended)

We've successfully used Test-Driven Development for both team names and manager names:

1. **🔴 RED**: Write a failing test for new functionality
2. **🟢 GREEN**: Write minimal code to make the test pass  
3. **🔵 REFACTOR**: Improve the code while keeping tests green

Example workflow:
```bash
# Start test watch mode
npm run test:watch

# Write your failing test
# Write implementation
# Tests should pass
# Refactor and improve

# Run full suite before committing
npm test
```

### 🗄️ Database Management

- **Development database**: `prisma/dev.db` (SQLite)
- **Schema changes**: Edit `prisma/schema.prisma`, then run `npx prisma db push`
- **View data**: Use Prisma Studio: `npx prisma studio`
- **Reset everything**: `npm run db:reset`

### 🧪 Testing Strategy

- **Unit tests**: Core functions and utilities
- **Component tests**: React components with user interactions
- **Integration tests**: API endpoints and database operations
- **E2E tests**: Full user workflows (Playwright)

All tests are configured to run in CI/CD pipeline automatically.

### 💡 Pro Tips

1. **Use your real ESPN data** for consistent development experience
2. **Write tests first** for new features (TDD)
3. **Keep tests running** in watch mode during development
4. **Use Prisma Studio** to inspect database state
5. **Reset database** if you want to start completely fresh

### 🐛 Troubleshooting

**Issue**: Page shows no leagues after refresh
**Solution**: Re-import your ESPN league through the League Integration tab

**Issue**: Tests failing after schema changes  
**Solution**: Update test data structures to match new schema

**Issue**: Database locked error
**Solution**: Stop all dev servers and run `npm run db:reset`