/**
 * tasa_auto_pago_standalone.js
 * FIX: Carga automática de tasa BCV en formularios INDEPENDIENTES
 * de PagoAdmin y CobroAdmin (no en inlines).
 *
 * Diferencia clave con tasa_auto_pago.js:
 *  - El JS de inline busca campos dentro del mismo .form-row (contexto de fila).
 *  - En standalone, fecha y tasa_cambio están en .form-row distintas.
 *    Se accede directamente por id_fecha / id_tasa_cambio / id_moneda.
 *
 * Comportamiento:
 *  1. Al cambiar `fecha` o `moneda`, llama GET /api/tasa/?fecha=YYYY-MM-DD.
 *  2. Si moneda == USD: fuerza tasa = 1.000000 y pone el campo readonly.
 *  3. Si moneda == VES y hay tasa: rellena tasa_cambio y pone readonly.
 *  4. Si moneda == VES y no hay tasa: muestra advertencia visible.
 *  5. Al cargar la página con fecha ya cargada, ejecuta una vez automáticamente.
 */
document.addEventListener('DOMContentLoaded', function () {
  var fechaInput  = document.getElementById('id_fecha');
  var tasaInput   = document.getElementById('id_tasa_cambio');
  var monedaInput = document.getElementById('id_moneda');

  // Formulario standalone de PagoAdmin/CobroAdmin: los tres campos deben existir.
  if (!fechaInput || !tasaInput) return;

  // Contenedor de aviso: se inserta justo después del campo tasa_cambio.
  var aviso = null;

  function mostrarAviso(msg) {
    if (!aviso) {
      aviso = document.createElement('p');
      aviso.className = 'help';
      aviso.style.cssText = 'color:#c00;font-weight:bold;margin-top:4px;';
      tasaInput.parentNode.appendChild(aviso);
    }
    aviso.textContent = msg;
    aviso.style.display = msg ? '' : 'none';
  }

  function ocultarAviso() {
    if (aviso) aviso.style.display = 'none';
  }

  function actualizarTasa() {
    var fecha  = fechaInput.value;
    var moneda = monedaInput ? monedaInput.value : 'USD';

    if (!fecha) return;

    if (moneda === 'USD') {
      tasaInput.value = '1.000000';
      tasaInput.setAttribute('readonly', 'readonly');
      ocultarAviso();
      return;
    }

    // VES: consultar la API
    fetch('/api/tasa/?fecha=' + fecha)
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (data.tasa) {
          tasaInput.value = data.tasa;
          tasaInput.setAttribute('readonly', 'readonly');
          ocultarAviso();
        } else {
          tasaInput.removeAttribute('readonly');
          mostrarAviso('\u26a0\ufe0f Sin tasa BCV para ' + fecha + '. El pago no ser\u00e1 guardado.');
        }
      })
      .catch(function (err) {
        console.error('Error obteniendo tasa BCV:', err);
      });
  }

  fechaInput.addEventListener('change', actualizarTasa);

  if (monedaInput) {
    monedaInput.addEventListener('change', actualizarTasa);
  }

  // Ejecutar una vez al cargar si la fecha ya tiene valor (formulario de edición).
  if (fechaInput.value) {
    actualizarTasa();
  }
});
