import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import HomePage from '../src/app/page';

describe('HomePage component (AC-1)', () => {
  it('renders landing page brand and monorepo online badge (covers: AC-1)', () => {
    render(<HomePage />);

    expect(screen.getByText('AoA')).toBeInTheDocument();
    expect(screen.getByText('agentsOnAir')).toBeInTheDocument();
    expect(screen.getByText('v0.1.0 scaffold')).toBeInTheDocument();
    expect(screen.getByText('Monorepo online')).toBeInTheDocument();
  });

  it('renders main heading and platform description (covers: AC-1)', () => {
    render(<HomePage />);

    const heading = screen.getByRole('heading', {
      level: 1,
      name: /Autonomous Engineer and Reviewer Platform/i,
    });
    expect(heading).toBeInTheDocument();

    expect(
      screen.getByText(/Develops, tests, and verifies code inside isolated sandboxes/i)
    ).toBeInTheDocument();
  });

  it('renders architecture cards for web, agent, services, and sandbox (covers: AC-1)', () => {
    render(<HomePage />);

    expect(screen.getByRole('heading', { level: 2, name: 'Web Console' })).toBeInTheDocument();
    expect(screen.getByText('apps/web')).toBeInTheDocument();

    expect(screen.getByRole('heading', { level: 2, name: 'Agent Engine' })).toBeInTheDocument();
    expect(screen.getByText('apps/agent')).toBeInTheDocument();

    expect(screen.getByRole('heading', { level: 2, name: 'Local Services' })).toBeInTheDocument();
    expect(screen.getByText('docker-compose.yml')).toBeInTheDocument();

    expect(screen.getByRole('heading', { level: 2, name: 'Execution Isolation' })).toBeInTheDocument();
    expect(screen.getByText('SandboxProvider')).toBeInTheDocument();
  });

  it('provides accessible semantic structure with landmarks (covers: AC-1)', () => {
    render(<HomePage />);

    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });
});
