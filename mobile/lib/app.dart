import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/api_client.dart';
import 'core/api_config.dart';
import 'core/auth_service.dart';
import 'core/device_fingerprint.dart';
import 'screens/auth/auth_gate.dart';
import 'services/ads_api.dart';
import 'services/auth_api.dart';
import 'services/cubes_api.dart';
import 'services/mining_api.dart';
import 'services/pix_api.dart';
import 'services/ranking_api.dart';
import 'services/rewarded_ad_service.dart';
import 'services/wallet_api.dart';
import 'theme/app_theme.dart';

class CubeMinePixApp extends StatelessWidget {
  const CubeMinePixApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider<AuthService>(create: (_) => FirebaseAuthService()),
        ProxyProvider<AuthService, ApiClient>(
          update: (_, authService, _) => ApiClient(
            baseUrl: ApiConfig.baseUrl,
            idTokenProvider: authService.getIdToken,
            deviceIdProvider: deviceFingerprint.getDeviceId,
          ),
        ),
        ProxyProvider<ApiClient, AuthApi>(update: (_, client, _) => HttpAuthApi(client)),
        ProxyProvider<ApiClient, CubesApi>(update: (_, client, _) => HttpCubesApi(client)),
        ProxyProvider<ApiClient, AdsApi>(update: (_, client, _) => HttpAdsApi(client)),
        ProxyProvider<ApiClient, MiningApi>(update: (_, client, _) => HttpMiningApi(client)),
        ProxyProvider<ApiClient, WalletApi>(update: (_, client, _) => HttpWalletApi(client)),
        ProxyProvider<ApiClient, PixApi>(update: (_, client, _) => HttpPixApi(client)),
        ProxyProvider<ApiClient, RankingApi>(update: (_, client, _) => HttpRankingApi(client)),
        Provider<RewardedAdService>(create: (_) => GoogleMobileAdsRewardedService()),
      ],
      child: MaterialApp(
        title: 'CubeMine Pix',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.dark,
        darkTheme: AppTheme.dark,
        themeMode: ThemeMode.dark,
        home: const AuthGate(),
      ),
    );
  }
}
