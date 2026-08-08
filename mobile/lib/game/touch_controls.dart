import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// Controles touch da Fase 1 -- layout pensado pra polegar em landscape:
/// bloco de movimento (esquerda/direita, segurado) no canto inferior
/// esquerdo, onde o polegar esquerdo já naturalmente descansa; ataques
/// (soco/chute/pular/defesa) no canto inferior direito, onde o polegar
/// direito alcança sem esticar. Move e defesa são "segurados" (estado
/// contínuo); pular/soco/chute disparam uma vez no toque (não esperam
/// soltar).
class TouchControls extends StatelessWidget {
  const TouchControls({
    super.key,
    required this.onMoveDirChanged,
    required this.onBlockChanged,
    required this.onJump,
    required this.onPunch,
    required this.onKick,
  });

  final ValueChanged<double> onMoveDirChanged;
  final ValueChanged<bool> onBlockChanged;
  final VoidCallback onJump;
  final VoidCallback onPunch;
  final VoidCallback onKick;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Positioned(left: 20, bottom: 20, child: _MovementPad(onMoveDirChanged: onMoveDirChanged)),
        Positioned(right: 20, bottom: 12, child: _ActionCluster(onBlockChanged: onBlockChanged, onJump: onJump, onPunch: onPunch, onKick: onKick)),
      ],
    );
  }
}

class _MovementPad extends StatefulWidget {
  const _MovementPad({required this.onMoveDirChanged});

  final ValueChanged<double> onMoveDirChanged;

  @override
  State<_MovementPad> createState() => _MovementPadState();
}

class _MovementPadState extends State<_MovementPad> {
  bool _left = false;
  bool _right = false;

  void _recompute() {
    final dir = _left == _right ? 0.0 : (_left ? -1.0 : 1.0);
    widget.onMoveDirChanged(dir);
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _ControlButton(
          key: const Key('fight_move_left_button'),
          color: AppColors.neonBlue,
          onPressChanged: (held) {
            _left = held;
            _recompute();
          },
          child: const Icon(Icons.chevron_left, color: Colors.white, size: 32),
        ),
        const SizedBox(width: 14),
        _ControlButton(
          key: const Key('fight_move_right_button'),
          color: AppColors.neonBlue,
          onPressChanged: (held) {
            _right = held;
            _recompute();
          },
          child: const Icon(Icons.chevron_right, color: Colors.white, size: 32),
        ),
      ],
    );
  }
}

class _ActionCluster extends StatelessWidget {
  const _ActionCluster({
    required this.onBlockChanged,
    required this.onJump,
    required this.onPunch,
    required this.onKick,
  });

  final ValueChanged<bool> onBlockChanged;
  final VoidCallback onJump;
  final VoidCallback onPunch;
  final VoidCallback onKick;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 216,
      height: 172,
      child: Stack(
        children: [
          Positioned(
            top: 0,
            left: 76,
            child: _ControlButton(
              key: const Key('fight_jump_button'),
              color: AppColors.neonBlue,
              onPressChanged: (pressed) {
                if (pressed) onJump();
              },
              child: const Icon(Icons.arrow_upward, color: Colors.white),
            ),
          ),
          Positioned(
            bottom: 28,
            left: 0,
            child: _ControlButton(
              key: const Key('fight_punch_button'),
              color: AppColors.epicGold,
              onPressChanged: (pressed) {
                if (pressed) onPunch();
              },
              child: const Text('SOCO', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12)),
            ),
          ),
          Positioned(
            bottom: 28,
            right: 0,
            child: _ControlButton(
              key: const Key('fight_kick_button'),
              color: AppColors.danger,
              onPressChanged: (pressed) {
                if (pressed) onKick();
              },
              child: const Text('CHUTE', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12)),
            ),
          ),
          Positioned(
            bottom: 0,
            left: 76,
            child: _ControlButton(
              key: const Key('fight_block_button'),
              color: AppColors.neonPurple,
              onPressChanged: onBlockChanged,
              child: const Icon(Icons.shield, color: Colors.white),
            ),
          ),
        ],
      ),
    );
  }
}

/// Botão redondo genérico -- [onPressChanged] recebe true no toque e false
/// ao soltar/cancelar. Quem usa decide se liga pro "held" (movimento,
/// defesa) ou só reage ao `true` (pular/soco/chute -- dispara uma vez,
/// ignora o `false` do soltar).
class _ControlButton extends StatefulWidget {
  const _ControlButton({super.key, required this.child, required this.color, required this.onPressChanged});

  static const double _size = 64;

  final Widget child;
  final Color color;
  final ValueChanged<bool> onPressChanged;

  @override
  State<_ControlButton> createState() => _ControlButtonState();
}

class _ControlButtonState extends State<_ControlButton> {
  bool _pressed = false;

  void _setPressed(bool value) {
    if (_pressed == value) return;
    setState(() => _pressed = value);
    widget.onPressChanged(value);
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTapDown: (_) => _setPressed(true),
      onTapUp: (_) => _setPressed(false),
      onTapCancel: () => _setPressed(false),
      child: Container(
        width: _ControlButton._size,
        height: _ControlButton._size,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: widget.color.withValues(alpha: _pressed ? 0.55 : 0.22),
          border: Border.all(color: widget.color, width: 2),
        ),
        child: widget.child,
      ),
    );
  }
}
