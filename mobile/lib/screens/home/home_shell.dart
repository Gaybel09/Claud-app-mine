import 'package:flutter/material.dart';

import '../../widgets/app_background.dart';
import '../cube/cube_screen.dart';
import '../wallet/wallet_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  static const _screens = [CubeScreen(), WalletScreen()];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: AppBackground(child: SafeArea(child: _screens[_index])),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (index) => setState(() => _index = index),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.widgets_outlined),
            selectedIcon: Icon(Icons.widgets),
            label: 'Cubo',
          ),
          NavigationDestination(
            icon: Icon(Icons.account_balance_wallet_outlined),
            selectedIcon: Icon(Icons.account_balance_wallet),
            label: 'Carteira',
          ),
        ],
      ),
    );
  }
}
