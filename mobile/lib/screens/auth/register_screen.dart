import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_exception.dart';
import '../../core/auth_exception.dart';
import '../../core/auth_service.dart';
import '../../services/auth_api.dart';
import '../../widgets/app_background.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _phoneController = TextEditingController();

  bool _isSubmitting = false;
  String? _errorMessage;

  /// Distinto de um erro genérico: significa que a conta (no Firebase e/ou
  /// no backend) muito provavelmente JÁ existe -- o cenário mais comum é
  /// uma tentativa anterior ter criado a conta de verdade nos dois lados,
  /// mas o app ter mostrado erro porque a resposta de sucesso não chegou
  /// (ex: instabilidade de rede, cold start do backend). Nesse caso a ação
  /// certa não é "tentar de novo criar", é "entrar" -- ver botão abaixo.
  bool _accountAlreadyExists = false;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
      _accountAlreadyExists = false;
    });

    try {
      final authService = context.read<AuthService>();
      final authApi = context.read<AuthApi>();

      await authService.registerWithEmailPassword(
        _emailController.text.trim(),
        _passwordController.text,
      );
      final phone = _phoneController.text.trim();
      await authApi.register(phone: phone.isEmpty ? null : phone);
      // O AuthGate escuta authStateChanges() e troca de tela sozinho assim
      // que o Firebase confirma o cadastro.
    } on AuthException catch (e) {
      setState(() {
        _errorMessage = e.message;
        _accountAlreadyExists = e.code == 'email-already-in-use';
      });
    } on ApiException catch (e) {
      // 409 = POST /auth/register já tinha criado o usuário antes (mesmo
      // firebase_uid) -- ver app/modules/auth/router.py. Só acontece na
      // prática se o passo anterior (Firebase) foi bem-sucedido silenciosamente
      // (ex: sessão do Firebase já autenticada de uma tentativa anterior).
      setState(() {
        _errorMessage = e.statusCode == 409
            ? 'Você já tem uma conta. Toque em "Já tenho conta" para entrar.'
            : e.message;
        _accountAlreadyExists = e.statusCode == 409;
      });
    } catch (_) {
      setState(() => _errorMessage = 'Não foi possível criar a conta. Tente novamente.');
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Criar conta')),
      extendBodyBehindAppBar: true,
      body: AppBackground(
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Form(
                key: _formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextFormField(
                      key: const Key('register_email_field'),
                      controller: _emailController,
                      keyboardType: TextInputType.emailAddress,
                      decoration: const InputDecoration(labelText: 'E-mail'),
                      validator: (value) =>
                          (value == null || !value.contains('@')) ? 'Informe um e-mail válido' : null,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      key: const Key('register_password_field'),
                      controller: _passwordController,
                      obscureText: true,
                      decoration: const InputDecoration(labelText: 'Senha'),
                      validator: (value) =>
                          (value == null || value.length < 6) ? 'Mínimo de 6 caracteres' : null,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      key: const Key('register_phone_field'),
                      controller: _phoneController,
                      keyboardType: TextInputType.phone,
                      decoration: const InputDecoration(labelText: 'Telefone (opcional)'),
                    ),
                    if (_errorMessage != null) ...[
                      const SizedBox(height: 16),
                      Text(
                        _errorMessage!,
                        key: const Key('register_error_text'),
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: Theme.of(context).colorScheme.error,
                            ),
                      ),
                    ],
                    const SizedBox(height: 24),
                    ElevatedButton(
                      key: const Key('register_submit_button'),
                      onPressed: _isSubmitting ? null : _submit,
                      child: _isSubmitting
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('CRIAR CONTA'),
                    ),
                    if (_accountAlreadyExists) ...[
                      const SizedBox(height: 12),
                      TextButton(
                        key: const Key('register_go_to_login_button'),
                        onPressed: () => Navigator.of(context).pop(),
                        child: const Text('Já tenho conta'),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
