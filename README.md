# 🏪 Golbazaar React App

A modern React frontend for the Golbazaar Frappe application.

## 🚀 Features

- **React 18** with TypeScript
- **Modern UI Components** with responsive design
- **Dashboard** with statistics and quick actions
- **Settings Page** for configuration
- **Frappe Integration** with API calls
- **Webpack** for bundling and development

## 📁 Project Structure

```
apps/golbazaar/
├── golbazaar/
│   ├── public/
│   │   ├── js/
│   │   │   ├── components/          # React components
│   │   │   │   ├── Dashboard.tsx
│   │   │   │   └── Settings.tsx
│   │   │   ├── App.tsx              # Main React app
│   │   │   ├── index.tsx            # React entry point
│   │   │   ├── styles.css           # Global styles
│   │   │   └── index.html           # HTML template
│   │   └── dist/                    # Built assets
│   └── www/
│       ├── golbazaar_react.py       # Frappe page controller
│       └── golbazaar_react.html     # Frappe page template
├── package.json                     # Node.js dependencies
├── webpack.config.js               # Webpack configuration
├── tsconfig.json                   # TypeScript configuration
└── dev.sh                          # Development script
```

## 🛠️ Development

### Prerequisites

- Node.js 16+ 
- npm or yarn
- Frappe Bench running

### Quick Start

1. **Start development server:**
   ```bash
   cd apps/golbazaar
   ./dev.sh
   ```

2. **Or manually:**
   ```bash
   cd apps/golbazaar
   npm install
   npm run dev
   ```

3. **Build for production:**
   ```bash
   npm run build
   bench build --app golbazaar
   ```

### Development URLs

- **React Dev Server:** http://localhost:3000
- **Frappe Integration:** http://localhost:8000/golbazaar_react

## 🔧 Configuration

### Webpack Configuration

The `webpack.config.js` file handles:
- TypeScript compilation
- CSS processing
- Asset bundling
- Development server

### Frappe Integration

The React app integrates with Frappe through:
- **Page Route:** `/golbazaar_react`
- **Asset Loading:** `/assets/golbazaar/dist/golbazaar.bundle.js`
- **API Calls:** Frappe's REST API

## 📱 Components

### Dashboard
- Statistics cards (Users, Orders, Revenue, Growth)
- Recent activity feed
- Quick action buttons
- Responsive grid layout

### Settings
- General app settings
- Theme selection
- Language preferences
- User information display

## 🎨 Styling

- **CSS Modules** for component styling
- **Responsive Design** with mobile-first approach
- **Modern UI** with gradients and shadows
- **Consistent Color Scheme** with CSS variables

## 🔌 API Integration

The app integrates with Frappe's API:

```typescript
// Fetch user data
fetch('/api/method/frappe.auth.get_logged_user')
  .then(response => response.json())
  .then(data => setUser(data.message));
```

## 🚀 Deployment

1. **Build React app:**
   ```bash
   npm run build
   ```

2. **Build Frappe app:**
   ```bash
   bench build --app golbazaar
   ```

3. **Migrate site:**
   ```bash
   bench --site your-site.local migrate
   ```

## 🧪 Testing

The React app includes:
- TypeScript for type safety
- Component-based architecture
- Error boundaries
- Loading states

## 📚 Next Steps

- Add more React components
- Implement state management (Redux/Zustand)
- Add unit tests (Jest/React Testing Library)
- Add charting library (Chart.js/D3.js)
- Implement real-time updates (WebSocket)
- Add PWA features

## 🤝 Contributing

1. Create feature branches
2. Follow TypeScript best practices
3. Test components thoroughly
4. Update documentation

## 📄 License

MIT License - see LICENSE file for details.