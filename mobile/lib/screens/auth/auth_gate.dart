import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/auth_service.dart';
import '../home/home_shell.dart';
import 'login_screen.dart';

/// Decide entre tela de login e o app autenticado com base no estado do
/// Firebase Auth -- reage a login/logout automaticamente via stream.
class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    final authService = context.read<AuthService>();
    return StreamBuilder<AppAuthUser?>(
      stream: authService.authStateChanges(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
        if (snapshot.data == null) {
          return const LoginScreen();
        }
        return const HomeShell();
      },
    );
  }
}
