import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './editorial.css'
import './workspace.css'
import './visual-fidelity.css'
import './product-ux.css'
import './screenshot-refinement.css'
import './workbench-polish.css'
import './interaction-hotfix.css'

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
