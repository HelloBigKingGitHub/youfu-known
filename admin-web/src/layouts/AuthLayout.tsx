import { Box, Flex, Text, VStack } from '@chakra-ui/react'
import { Outlet } from 'react-router-dom'

export function AuthLayout() {
  return (
    <Flex
      minH="100vh"
      align="center"
      justify="center"
      bg="ink.950"
      position="relative"
      overflow="hidden"
      px={4}
    >
      <Box
        position="absolute"
        inset={0}
        opacity={0.35}
        bgGradient="radial(at 20% 20%, copper.500/15, transparent 55%), radial(at 80% 70%, signal.500/12, transparent 60%)"
        pointerEvents="none"
      />
      <VStack
        spacing={6}
        position="relative"
        w="full"
        maxW="420px"
        align="stretch"
      >
        <Box textAlign="center">
          <Text
            fontFamily="heading"
            fontSize="3xl"
            color="copper.400"
            letterSpacing="0.04em"
          >
            youfu-known
          </Text>
          <Text mt={1} fontSize="sm" color="whiteAlpha.600">
            管理后台
          </Text>
        </Box>
        <Box
          bg="ink.900"
          borderRadius="lg"
          borderWidth="1px"
          borderColor="whiteAlpha.100"
          boxShadow="0 30px 80px -30px rgba(0,0,0,0.7)"
          p={8}
        >
          <Outlet />
        </Box>
      </VStack>
    </Flex>
  )
}
