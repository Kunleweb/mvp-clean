import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'CLEAN Data Platform - Quality Dashboard',
  description: 'Enterprise Data Quality Monitoring and Governance',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div style={{ display: 'flex', minHeight: '100vh', flexDirection: 'column' }}>
          {/* Modern Header */}
          <header style={{ 
            backgroundColor: 'var(--card)', 
            borderBottom: '1px solid var(--border)',
            padding: '1rem 2rem',
            boxShadow: 'var(--shadow-sm)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', maxWidth: '1280px', margin: '0 auto', width: '100%' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <div style={{ 
                  backgroundColor: 'var(--primary)', 
                  color: 'white', 
                  width: '32px', 
                  height: '32px', 
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 'bold'
                }}>
                  C
                </div>
                <h1 style={{ fontSize: '1.25rem', margin: 0, color: 'var(--foreground)' }}>CLEAN Platform</h1>
              </div>
              <nav style={{ display: 'flex', gap: '1.5rem', fontSize: '0.875rem', fontWeight: '500', color: 'var(--muted-foreground)' }}>
                <span style={{ color: 'var(--primary)' }}>Dashboard</span>
                <span>Assets</span>
                <span>Settings</span>
              </nav>
            </div>
          </header>
          
          {/* Main Content Area */}
          <main style={{ flex: 1 }}>
            {children}
          </main>
          
          {/* Professional Footer */}
          <footer style={{ 
            marginTop: 'auto', 
            borderTop: '1px solid var(--border)', 
            padding: '1.5rem',
            textAlign: 'center',
            backgroundColor: 'var(--card)'
          }}>
            <p style={{ margin: 0 }}>© {new Date().getFullYear()} CLEAN Data Platform. All rights reserved.</p>
          </footer>
        </div>
      </body>
    </html>
  );
}
