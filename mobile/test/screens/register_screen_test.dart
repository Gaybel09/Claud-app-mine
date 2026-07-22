import 'package:cubemine_pix/core/api_exception.dart';
import 'package:cubemine_pix/core/auth_service.dart';
import 'package:cubemine_pix/screens/auth/register_screen.dart';
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
    child: MaterialApp(theme: AppTheme.dark, home: const RegisterScreen()),
  );
}

void main() {
  group('RegisterScreen', () {
    testWidgets('registers with Firebase and forwards the optional phone to the backend', (tester) async {
      final authService = FakeAuthService();
      final authApi = FakeAuthApi();
      await tester.pumpWidget(_wrap(authService: authService, authApi: authApi));

      await tester.enterText(find.byKey(const Key('register_email_field')), 'new@example.com');
      await tester.enterText(find.byKey(const Key('register_password_field')), 'password123');
      await tester.enterText(find.byKey(const Key('register_phone_field')), '+5511999990000');
      await tester.tap(find.byKey(const Key('register_submit_button')));
      await tester.pumpAndSettle();

      expect(authApi.registerCalled, isTrue);
      expect(authApi.registeredPhone, '+5511999990000');
      expect(authService.currentUser?.email, 'new@example.com');
    });

    testWidgets('leaves phone null when the field is left empty', (tester) async {
      final authService = FakeAuthService();
      final authApi = FakeAuthApi();
      await tester.pumpWidget(_wrap(authService: authService, authApi: authApi));

      await tester.enterText(find.byKey(const Key('register_email_field')), 'new2@example.com');
      await tester.enterText(find.byKey(const Key('register_password_field')), 'password123');
      await tester.tap(find.byKey(const Key('register_submit_button')));
      await tester.pumpAndSettle();

      expect(authApi.registerCalled, isTrue);
      expect(authApi.registeredPhone, isNull);
    });

    testWidgets('shows an error message when the backend rejects registration', (tester) async {
      final authService = FakeAuthService();
      final authApi = FakeAuthApi()
        ..throwOnRegister = const ApiException(statusCode: 409, message: 'User already registered');
      await tester.pumpWidget(_wrap(authService: authService, authApi: authApi));

      await tester.enterText(find.byKey(const Key('register_email_field')), 'dup@example.com');
      await tester.enterText(find.byKey(const Key('register_password_field')), 'password123');
      await tester.tap(find.byKey(const Key('register_submit_button')));
      await tester.pumpAndSettle();

      expect(find.text('User already registered'), findsOneWidget);
    });
  });
}
