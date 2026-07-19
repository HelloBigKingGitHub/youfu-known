// Chakra UI 主题 - 现代 SaaS 风格 (Linear / Notion / Vercel 感觉)
// 品牌色 #3b82f6 (Tailwind blue-500), 中性灰分层, 圆角加大, 阴影分层
import { extendTheme, type ThemeConfig } from '@chakra-ui/react'

const config: ThemeConfig = {
  initialColorMode: 'light',
  useSystemColorMode: false,
}

export const theme = extendTheme({
  config,
  fonts: {
    heading: `'Inter', 'PingFang SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`,
    body: `'Inter', 'PingFang SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`,
    mono: `'JetBrains Mono', 'SFMono-Regular', Menlo, Consolas, monospace`,
  },
  colors: {
    brand: {
      50: '#eff6ff',
      100: '#dbeafe',
      200: '#bfdbfe',
      300: '#93c5fd',
      400: '#60a5fa',
      500: '#3b82f6',
      600: '#2563eb',
      700: '#1d4ed8',
      800: '#1e40af',
      900: '#1e3a8a',
    },
    surface: {
      sunken: '#f8f9fb',
      border: '#e8eaed',
      subtle: '#f1f3f5',
    },
  },
  radii: {
    sm: '6px',
    md: '10px',
    lg: '14px',
    xl: '18px',
    '2xl': '24px',
    '3xl': '32px',
  },
  shadows: {
    xs: '0 1px 2px 0 rgba(15, 23, 42, 0.04)',
    sm: '0 1px 3px 0 rgba(15, 23, 42, 0.06), 0 1px 2px 0 rgba(15, 23, 42, 0.04)',
    md: '0 4px 8px -2px rgba(15, 23, 42, 0.08), 0 2px 4px -2px rgba(15, 23, 42, 0.05)',
    lg: '0 10px 20px -4px rgba(15, 23, 42, 0.08), 0 4px 8px -4px rgba(15, 23, 42, 0.05)',
    xl: '0 20px 40px -8px rgba(15, 23, 42, 0.12), 0 8px 16px -8px rgba(15, 23, 42, 0.06)',
  },
  styles: {
    global: {
      body: {
        bg: 'gray.50',
        color: 'gray.800',
      },
    },
  },
  components: {
    Button: {
      defaultProps: {
        colorScheme: 'brand',
      },
      baseStyle: {
        fontWeight: 'semibold',
      },
    },
    Tabs: {
      variants: {
        'soft-rounded': {
          tab: {
            fontSize: 'sm',
            fontWeight: 'semibold',
            color: 'gray.500',
            borderRadius: 'lg',
            px: { base: 3, md: 5 },
            py: { base: 2, md: 2.5 },
            transition: 'all 0.15s',
            _hover: { color: 'gray.700' },
            _selected: {
              bg: 'white',
              color: 'brand.600',
              boxShadow: 'sm',
            },
          },
          tablist: {
            bg: 'surface.sunken',
            borderRadius: 'xl',
            p: 1,
            border: '1px',
            borderColor: 'surface.border',
            gap: 1,
          },
        },
      },
    },
  },
})
