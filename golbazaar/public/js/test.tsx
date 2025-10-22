import React from 'react';
import ReactDOM from 'react-dom/client';

// Simple test component
const TestApp = () => {
  return React.createElement('div', {
    style: {
      padding: '2rem',
      textAlign: 'center',
      backgroundColor: '#f8f9fa',
      minHeight: '100vh'
    }
  }, [
    React.createElement('h1', { key: 'title' }, '🏪 Golbazaar React Test'),
    React.createElement('p', { key: 'status' }, 'React is working!'),
    React.createElement('button', {
      key: 'button',
      onClick: () => alert('React click works!'),
      style: {
        padding: '10px 20px',
        backgroundColor: '#667eea',
        color: 'white',
        border: 'none',
        borderRadius: '5px',
        cursor: 'pointer'
      }
    }, 'Test Button')
  ]);
};

// Mount the app immediately
console.log('React bundle loaded, attempting to mount...');

const rootElement = document.getElementById('root');
if (rootElement) {
  console.log('Root element found, mounting React app');
  const root = ReactDOM.createRoot(rootElement);
  root.render(React.createElement(TestApp));
  console.log('React app mounted successfully');
} else {
  console.error('Root element not found!');
}
