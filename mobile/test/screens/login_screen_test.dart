import 'package:cubemine_pix/core/api_exception.dart';
import 'package:cubemine_pix/core/auth_service.dart';
import 'package:cubemine_pix/screens/auth/login_screen.dart';
import 'package:cubemine_pix/services/auth_api.dart';
import 'package:cubemine_pix/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import '../fakes/fake_services.dart';

Widget _wrap({required FakeAuthService authService, required FakeAuthApi authApi}) {
  return MultiProvider(
    providers: [
      Provider<AuthService>.value(value: authService),
      Provider<AuthApi>.value(value: authApi),
    ],
    child: MaterialApp(theme: AppTheme.dark, home: const LoginScreen()),
  );
}

void main() {
  group('LoginScreen', () {
    testWidgets('shows validation errors and does not call the backend for empty fields', (tester) async {
      final authService = FakeAuthService();
      final authApi = FakeAuthApi();
      await tester.pumpWidget(_wrap(authService: authService, authApi: authApi));

      await tester.tap(find.byKey(const Key('login_submit_button')));
      await tester.pump();

      expect(find.text('Informe um e-mail válido'), findsOneWidget);
      expect(find.text('Mínimo de 6 caracteres'), findsOneWidget);
      expect(authApi.loginCalled, isFalse);
    });

    testWidgets('signs in with Firebase and calls the backend login endpoint on success', (tester) async {
      final authService = FakeAuthService();
      final authApi = FakeAuthApi();
      await tester.pumpWidget(_wrap(authService: authService, authApi: authApi));

      await tester.enterText(find.byKey(const Key('login_email_field')), 'user@example.com');
      await tester.enterText(find.byKey(const Key('login_password_field')), 'password123');
      await tester.tap(find.byKey(const Key('login_submit_button')));
      await tester.pumpAndSettle();

      expect(authApi.loginCalled, isTrue);
      expect(authService.currentUser?.email, 'user@example.com');
    });

    testWidgets('shows the backend error message when login is rejected', (tester) async {
      final authService = FakeAuthService();
      final authApi = FakeAuthApi()
        ..throwOnLogin = const ApiException(statusCode: 403, message: 'User is blocked');
      await tester.pumpWidget(_wrap(authService: authService, authApi: authApi));

      await tester.enterText(find.byKey(const Key('login_email_field')), 'user@example.com');
      await tester.enterText(find.byKey(const Key('login_password_field')), 'password123');
      await tester.tap(find.byKey(const Key('login_submit_button')));
      await tester.pumpAndSettle();

      expect(find.text('User is blocked'), findsOneWidget);
    });
  });
}
