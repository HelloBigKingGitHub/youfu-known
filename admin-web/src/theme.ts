import { extendTheme } from '@chakra-ui/react'

export const theme = extendTheme({
  colors: {
    ink: {
      950: '#0c1117',
      900: '#121a24',
      800: '#1a2633',
      700: '#263746',
    },
    copper: {
      300: '#f4c98a',
      400: '#e6a95d',
      500: '#c9823b',
      600: '#a6622b',
    },
    signal: {
      300: '#8ce3d2',
      400: '#52c7b5',
      500: '#2aa18f',
    },
  },
  fonts: {
    heading: "'Iowan Old Style', 'Noto Serif SC', Georgia, serif",
    body: "'Avenir Next', 'Noto Sans SC', Arial, sans-serif",
  },
  styles: {
    global: {
      body: {
        bg: 'ink.950',
        color: 'whiteAlpha.900',
      },
      '*:focus-visible': {
        outline: '2px solid',
        outlineColor: 'signal.300',
        outlineOffset: '3px',
      },
    },
  },
  components: {
    Button: {
      defaultProps: {
        colorScheme: 'signal',
      },
    },
    Table: {
      variants: {
        admin: {
          th: {
            color: 'whiteAlpha.600',
            fontSize: 'xs',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            borderColor: 'whiteAlpha.100',
          },
          td: {
            borderColor: 'whiteAlpha.100',
          },
        },
      },
    },
  },
})
