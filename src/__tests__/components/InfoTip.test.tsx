import { render, screen } from '@testing-library/react'
import InfoTip from '@/components/InfoTip'

describe('InfoTip', () => {
  it('renders the trigger child', () => {
    render(<InfoTip content="hello">Trigger</InfoTip>)
    expect(screen.getByText('Trigger')).toBeInTheDocument()
  })

  it('renders the tooltip content in the DOM (so it is hover-discoverable)', () => {
    render(<InfoTip content="hello world">⚡</InfoTip>)
    expect(screen.getByText('hello world')).toBeInTheDocument()
  })

  it('links the trigger to the tooltip via aria-describedby', () => {
    render(<InfoTip content="hello">Trigger</InfoTip>)
    const trigger = screen.getByText('Trigger')
    const describedBy = trigger.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    const tip = document.getElementById(describedBy!)
    expect(tip).not.toBeNull()
    expect(tip!.textContent).toBe('hello')
  })

  it('accepts ReactNode content (renders a swatch alongside text)', () => {
    render(
      <InfoTip content={<><span data-testid="swatch" />structured</>}>
        ⚡
      </InfoTip>,
    )
    expect(screen.getByTestId('swatch')).toBeInTheDocument()
    expect(screen.getByText('structured')).toBeInTheDocument()
  })
})
