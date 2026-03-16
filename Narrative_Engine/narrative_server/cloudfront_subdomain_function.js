/**
 * CloudFront Function (viewer request): map subdomain to S3 path web/<subdomain>/
 *
 * Use with one S3 bucket and one CloudFront distribution. Alternate domain: *.play.<yourdomain.com>
 * Request: https://the-legend-s-choice.play.narrator.com/  → origin path: web/the-legend-s-choice/index.html
 * Request: https://the-legend-s-choice.play.narrator.com/foo.pck → origin path: web/the-legend-s-choice/foo.pck
 *
 * Publish: AWS Console → CloudFront → Functions → Create function → paste this code,
 * then associate with your distribution's default (or wildcard) behavior as "Viewer request".
 */
function handler(event) {
    var request = event.request;
    var host = request.headers.host ? request.headers.host.value : '';
    var uri = request.uri || '/';

    // Extract subdomain (first label before .play.domain or similar)
    // e.g. the-legend-s-choice.play.narrator.com -> the-legend-s-choice
    var parts = host.split('.');
    if (parts.length < 2) {
        return request;
    }
    var subdomain = parts[0].toLowerCase();

    // Sanitize: only allow alphanumeric and hyphen (slug)
    subdomain = subdomain.replace(/[^a-z0-9-]/g, '');
    if (!subdomain) {
        return request;
    }

    // Rewrite URI so origin sees web/<subdomain>/<path>
    var path = uri.endsWith('/') ? uri + 'index.html' : uri;
    if (!path.startsWith('/')) {
        path = '/' + path;
    }
    request.uri = '/web/' + subdomain + path;
    return request;
}
