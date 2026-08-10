// Écran UI : détail d'un reçu de paiement (US-5.5, #38 · ADR-0040).
//
// Charge le reçu via `GetReceiptDetail` (injecté) et affiche : salon, numéro de
// reçu, date, prestations, montant, mode et statut. Propose une action
// « Partager » via le partage natif du téléphone (`share_plus`) — **aucune**
// impression thermique réelle depuis le mobile (ADR-0040 §6). États :
// chargement / session requise / introuvable / erreur.

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../../../application/auth_session.dart';
import '../../../application/ports/receipt_gateway.dart';
import '../../../application/use_cases/get_receipt_detail.dart';
import '../../../domain/receipt/receipt.dart';
import '../booking/booking_flow_screen.dart' show LoginRequester;
import '../booking/booking_labels.dart';
import 'receipt_share_text.dart';

/// Déclenche le partage natif du texte du reçu — substituable en test.
typedef ReceiptShareInvoker = Future<void> Function(String text);

Future<void> _defaultShare(String text) async {
  await SharePlus.instance.share(ShareParams(text: text));
}

class ReceiptDetailScreen extends StatefulWidget {
  const ReceiptDetailScreen({
    super.key,
    required this.paymentId,
    required this.getReceiptDetail,
    required this.session,
    required this.onRequireLogin,
    this.shareInvoker = _defaultShare,
  });

  final String paymentId;
  final GetReceiptDetail getReceiptDetail;
  final AuthSession session;
  final LoginRequester onRequireLogin;
  final ReceiptShareInvoker shareInvoker;

  @override
  State<ReceiptDetailScreen> createState() => _ReceiptDetailScreenState();
}

class _ReceiptDetailScreenState extends State<ReceiptDetailScreen> {
  bool _loading = true;
  bool _needsLogin = false;
  bool _notFound = false;
  String? _error;
  Receipt? _receipt;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _error = null;
      _needsLogin = false;
      _notFound = false;
    });

    var token = await widget.session.currentToken();
    if (token == null) {
      if (!mounted) return;
      final ok = await widget.onRequireLogin(context);
      if (!ok) {
        _showNeedsLogin();
        return;
      }
      token = await widget.session.currentToken();
      if (token == null) {
        _showNeedsLogin();
        return;
      }
    }

    try {
      final receipt = await widget.getReceiptDetail.call(
        paymentId: widget.paymentId,
        accessToken: token,
      );
      if (!mounted) return;
      setState(() {
        _receipt = receipt;
        _loading = false;
      });
    } on UnauthorizedException {
      await widget.session.clear();
      if (!mounted) return;
      setState(() {
        _loading = false;
        _needsLogin = true;
        _error = 'Session expirée, veuillez vous reconnecter.';
      });
    } on ReceiptNotFoundException {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _notFound = true;
      });
    } on ReceiptGatewayException catch (exc) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = exc.message;
      });
    }
  }

  void _showNeedsLogin() {
    if (!mounted) return;
    setState(() {
      _loading = false;
      _needsLogin = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    final receipt = _receipt;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Reçu'),
        actions: <Widget>[
          if (receipt != null)
            IconButton(
              icon: const Icon(Icons.share_outlined),
              tooltip: 'Partager',
              onPressed: () => widget.shareInvoker(formatReceiptShareText(receipt)),
            ),
        ],
      ),
      body: SafeArea(child: _buildBody()),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_needsLogin) {
      return _CenteredAction(
        message: _error ?? 'Connectez-vous pour voir ce reçu.',
        actionLabel: 'Se connecter',
        onAction: _load,
      );
    }
    if (_notFound) {
      return const _CenteredMessage('Ce reçu est introuvable.');
    }
    if (_error != null) {
      return _CenteredAction(
        message: _error!,
        actionLabel: 'Réessayer',
        onAction: _load,
      );
    }
    return _ReceiptBody(receipt: _receipt!);
  }
}

class _ReceiptBody extends StatelessWidget {
  const _ReceiptBody({required this.receipt});

  final Receipt receipt;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        Text(receipt.salonName, style: theme.textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(receipt.receiptNumber, style: theme.textTheme.bodyMedium),
        Text(formatFullDate(receipt.paidAt), style: theme.textTheme.bodyMedium),
        const Divider(height: 32),
        for (final line in receipt.lines) _ReceiptLineRow(line: line),
        if (receipt.lines.isNotEmpty) const Divider(height: 32),
        _KeyValueRow(label: 'Total', value: '${receipt.amount} FCFA'),
        _KeyValueRow(label: 'Mode de paiement', value: receipt.paymentMethod),
        _KeyValueRow(label: 'Statut', value: receipt.status),
        if (receipt.reference != null && receipt.reference!.trim().isNotEmpty)
          _KeyValueRow(label: 'Référence', value: receipt.reference!.trim()),
      ],
    );
  }
}

class _ReceiptLineRow extends StatelessWidget {
  const _ReceiptLineRow({required this.line});

  final ReceiptLine line;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: <Widget>[
          Expanded(child: Text(line.serviceName)),
          Text('${line.amount} FCFA'),
        ],
      ),
    );
  }
}

class _KeyValueRow extends StatelessWidget {
  const _KeyValueRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: <Widget>[
          Expanded(child: Text(label)),
          Text(value),
        ],
      ),
    );
  }
}

class _CenteredMessage extends StatelessWidget {
  const _CenteredMessage(this.message);

  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Retour à la liste'),
            ),
          ],
        ),
      ),
    );
  }
}

class _CenteredAction extends StatelessWidget {
  const _CenteredAction({
    required this.message,
    required this.actionLabel,
    required this.onAction,
  });

  final String message;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: onAction, child: Text(actionLabel)),
          ],
        ),
      ),
    );
  }
}
