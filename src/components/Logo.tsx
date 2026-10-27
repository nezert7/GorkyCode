import './Logo.css'

type LogoProps = {
  variant: 'start' | 'menu'
}

export default function Logo({ variant }: LogoProps) {
  return (
    <h1 className={`logo logo--${variant}`}>
      <span className="logo__your">YOUR</span>
      <span className="logo__adorable">adorable</span>
      <span className="logo__vorona">VORONA</span>
    </h1>
  )
}
