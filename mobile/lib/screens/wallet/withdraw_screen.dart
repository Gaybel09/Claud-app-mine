import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../controllers/withdraw_controller.dart';
import '../../models/withdrawal.dart';
import '../../services/auth_api.dart';
import '../../services/pix_api.dart';
import '../../theme/app_colors.dart';

class WithdrawScreen extends StatefulWidget {
  const WithdrawScreen({super.key, required this.availableBalance});

  final double availableBalance;

  @override
  State<WithdrawScreen> createState() => _WithdrawScreenState();
}

class _WithdrawScreenState extends State<WithdrawScreen> {
  late final WithdrawController _controller;
  final _formKey = GlobalKey<FormState>();
  final _amountController = TextEditingController();
  final _pixKeyController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _controller = WithdrawController(
      pixApi: context.read<PixApi>(),
      authApi: context.read<AuthApi>(),
    )..addListener(_onControllerChanged);
    _controller.loadProfile();
  }

  void _onControllerChanged() => setState(() {});

  @override
  void dispose() {
    _controller.removeListener(_onControllerChanged);
    _controller.dispose();
    _amountController.dispose();
    _pixKeyController.dispose();
    super.dispose();
  }

  String? _validateAmount(String? value) {
    if (value == null || value.trim().isEmpty) return 'Informe um valor.';
    final amount = double.tryParse(value.trim().replaceAll(',', '.'));
    if (amount == null || amount <= 0) return 'Informe um valor válido.';
    if (amount > widget.availableBalance) return 'Valor maior que o saldo disponível.';
    return null;
  }

  String? _validatePixKey(String? value) {
    if (_controller.registeredPixKey != null) return null;
    if (value == null || value.trim().isEmpty) return 'Informe sua chave Pix.';
    return null;
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;
    final amount = double.parse(_amountController.text.trim().replaceAll(',', '.'));
    final hasRegisteredKey = _controller.registeredPixKey != null;
    _controller.submit(
      amount: amount,
      pixKey: hasRegisteredKey ? null : _pixKeyController.text.trim(),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Sacar')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Center(child: _buildBody(context)),
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_controller.loadingProfile) {
      return const CircularProgressIndicator();
    }
    switch (_controller.stage) {
      case WithdrawStage.form:
        return _buildForm(context);
      case WithdrawStage.submitting:
        return const _StatusMessage(message: 'Enviando solicitação...', showSpinner: true);
      case WithdrawStage.processing:
        return _StatusMessage(
          key: const Key('withdraw_processing_message'),
          message: 'Saque solicitado, processando...',
          showSpinner: true,
        );
      case WithdrawStage.done:
        return _DoneState(
          withdrawal: _controller.withdrawal!,
          onClose: () => Navigator.of(context).pop(true),
        );
      case WithdrawStage.error:
        return _ErrorState(
          message: _controller.errorMessage ?? 'Erro desconhecido.',
          onRetry: _controller.resetToForm,
        );
    }
  }

  Widget _buildForm(BuildContext context) {
    return Form(
      key: _formKey,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Saldo disponível: R\$ ${widget.availableBalance.toStringAsFixed(2)}',
            style: Theme.of(context).textTheme.bodyLarge,
          ),
          const SizedBox(height: 24),
          TextFormField(
            key: const Key('withdraw_amount_field'),
            controller: _amountController,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Valor (R\$)'),
            validator: _validateAmount,
          ),
          const SizedBox(height: 16),
          if (_controller.registeredPixKey != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                'Chave Pix cadastrada: ${_controller.registeredPixKey}',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            )
          else
            TextFormField(
              key: const Key('withdraw_pix_key_field'),
              controller: _pixKeyController,
              decoration: const InputDecoration(
                labelText: 'Chave Pix',
                helperText: 'Você ainda não tem uma chave Pix cadastrada -- informe uma para este saque.',
              ),
              validator: _validatePixKey,
            ),
          const SizedBox(height: 24),
          ElevatedButton(
            key: const Key('withdraw_submit_button'),
            onPressed: _submit,
            child: const Text('SOLICITAR SAQUE'),
          ),
        ],
      ),
    );
  }
}

class _StatusMessage extends StatelessWidget {
  const _StatusMessage({super.key, required this.message, this.showSpinner = false});

  final String message;
  final bool showSpinner;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (showSpinner) ...[
          const CircularProgressIndicator(),
          const SizedBox(height: 24),
        ],
        Text(message, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
      ],
    );
  }
}

class _DoneState extends StatelessWidget {
  const _DoneState({required this.withdrawal, required this.onClose});

  final Withdrawal withdrawal;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final isPaid = withdrawal.status == 'paid';
    final isFailed = withdrawal.status == 'failed';
    final color = isPaid ? AppColors.success : (isFailed ? AppColors.danger : AppColors.mutedWhite);
    final icon = isPaid ? Icons.check_circle : (isFailed ? Icons.error : Icons.hourglass_top);
    final message = isPaid
        ? 'Saque de R\$ ${withdrawal.amount.toStringAsFixed(2)} confirmado!'
        : isFailed
            ? 'O saque não pôde ser concluído.'
            : 'Seu saque ainda está sendo processado -- confira o status na Carteira mais tarde.';

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: color, size: 64),
        const SizedBox(height: 16),
        Text(
          message,
          key: const Key('withdraw_done_message'),
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 24),
        ElevatedButton(onPressed: onClose, child: const Text('VOLTAR PARA A CARTEIRA')),
      ],
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.error_outline, color: Theme.of(context).colorScheme.error, size: 48),
        const SizedBox(height: 16),
        Text(
          message,
          key: const Key('withdraw_error_text'),
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyLarge,
        ),
        const SizedBox(height: 24),
        ElevatedButton(onPressed: onRetry, child: const Text('TENTAR DE NOVO')),
      ],
    );
  }
}
