# Development Guide

## Quick Start for Development

### 🚀 Setting Up Persistent Development Data

To avoid having to re-import your league data every time you refresh the page during development:

1. **Seed development data** (one-time setup):
   ```bash
   npm run seed:dev
   ```

2. **Your data will now persist!** The seeded league includes:
   - League: "JUICED (Dev League)" 
   - 10 teams with realistic names and stats
   - 5 sample MLB players
   - Proper manager names (no more cryptic IDs)

### 📊 Available Development Commands

```bash
# Seed development data
npm run seed:dev

# Reset database and reseed (if you want to start fresh)
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
2. **Access your persistent league**: Go to League Integration tab → Your "JUICED (Dev League)" should already be there
3. **Make changes to code**
4. **Refresh page** → Your data persists! No need to re-import
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

1. **Use the seeded data** for consistent development experience
2. **Write tests first** for new features (TDD)
3. **Keep tests running** in watch mode during development
4. **Use Prisma Studio** to inspect database state
5. **Reset database** if you want to start completely fresh

### 🐛 Troubleshooting

**Issue**: Page shows no leagues after refresh
**Solution**: Run `npm run seed:dev` to create persistent development data

**Issue**: Tests failing after schema changes  
**Solution**: Update test data structures to match new schema

**Issue**: Database locked error
**Solution**: Stop all dev servers and run `npm run db:reset`