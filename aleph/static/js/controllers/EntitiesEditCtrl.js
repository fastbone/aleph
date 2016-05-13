aleph.controller('EntitiesEditCtrl', ['$scope', '$http', '$uibModalInstance', 'Metadata', 'Session', 'Authz', 'Alert', 'Validation', 'entity', 'metadata', 'alerts',
    function($scope, $http, $uibModalInstance, Metadata, Session, Authz, Alert, Validation, entity, metadata, alerts) {

  $scope.entity = entity;
  $scope.entity.jurisdiction_code = entity.jurisdiction_code || null;
  $scope.originalName = entity.name + '';

  var initAlerts = function() {
    $scope.alertId = null;
    for (var i in alerts.results) {
      var alert = alerts.results[i];
      if (!alert.query_text && alert.entity_id == $scope.entity.id) {
        $scope.alertId = alert.id;
      }
    }
    $scope.entity.haveAlert = $scope.alertId != null;
  }

  initAlerts();

  $scope.canSave = function() {
    return $scope.editEntity.$valid;
  }

  $scope.cancel = function() {
    $uibModalInstance.dismiss('cancel');
  };

  $scope.save = function(form) {
    if (!$scope.canSave()) {
      return false;
    }
    var url = '/api/1/entities/' + $scope.entity.id;
    var res = $http.post(url, $scope.entity);
    res.then(function(res) {
      if ($scope.entity.haveAlert && !$scope.alertId) {
        Alert.create({entity_id: entity.id}).then(function() {
          $uibModalInstance.close(res.data);  
        });
      } else if (!$scope.entity.haveAlert && $scope.alertId) {
        Alert.delete($scope.alertId).then(function() {
          $uibModalInstance.close(res.data);  
        });
      } else {
        $uibModalInstance.close(res.data);
      }
    });
  };

}]);
